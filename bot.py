import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
)
from dotenv import load_dotenv

from optional_mode_v1_backend import evaluate_optional


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env faylni tekshiring.")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
INPUT_DIR = UPLOADS_DIR / "input"
RESULTS_DIR = UPLOADS_DIR / "results"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# Hozircha faqat PDF qabul qilamiz.
# Sabab: PDF 300 DPI render bo‘lgani uchun AI chizmani aniqroq tahlil qiladi.
ALLOWED_EXTENSIONS = {".pdf"}
TELEGRAM_MESSAGE_LIMIT = 3900


upload_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Chizmani yuklang")]
    ],
    resize_keyboard=True
)


def is_allowed_file(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def safe_filename(filename: str, default_name: str = "drawing.pdf") -> str:
    """
    Foydalanuvchi yuborgan filename ichidan faqat fayl nomini olamiz.
    Bu Windows/Linux path muammolarining oldini oladi.
    """
    name = Path(filename).name.strip()

    if not name:
        return default_name

    return name


def make_request_dir(message: Message) -> Path:
    request_dir = INPUT_DIR / f"{message.chat.id}_{message.message_id}"
    request_dir.mkdir(parents=True, exist_ok=True)
    return request_dir


def make_result_dir(message: Message) -> Path:
    result_dir = RESULTS_DIR / f"{message.chat.id}_{message.message_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir


def cleanup_dir(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("Temp papkani o‘chirishda xatolik: %s", path)


async def send_long_message(message: Message, text: str) -> None:
    """
    Telegram bitta xabarda taxminan 4096 belgigacha yuboradi.
    Xabar uzun bo‘lib ketsa, bo‘lib yuboramiz.
    """
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        await message.answer(text)
        return

    parts = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > TELEGRAM_MESSAGE_LIMIT:
            parts.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        parts.append(current)

    for part in parts:
        await message.answer(part)


def build_score_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "📋 Mezonlar jadvali mavjud emas."

    lines = ["📋 Mezonlar bo‘yicha natija:"]

    for index, row in enumerate(rows, start=1):
        criterion = str(row.get("criterion", "Noma’lum mezon"))
        score = float(row.get("score", 0))
        max_score = float(row.get("max_score", 0))
        comment = str(row.get("comment", "") or "").strip()

        if score.is_integer():
            score_text = str(int(score))
        else:
            score_text = str(round(score, 2))

        if max_score.is_integer():
            max_score_text = str(int(max_score))
        else:
            max_score_text = str(round(max_score, 2))

        lines.append(f"{index}. {criterion} — {score_text}/{max_score_text}")

        if comment:
            lines.append(f"   Izoh: {comment}")

    return "\n".join(lines)


def format_result_message(result: dict[str, Any]) -> str:
    total_score = int(result.get("total_score", 0))
    details = result.get("details", {}) or {}
    table_json = result.get("table_json", []) or []

    grade_label = details.get("grade_label", "Noma’lum")
    confidence_label = details.get("confidence_label", "unknown")

    feedback = details.get("feedback", []) or []
    errors = details.get("errors", []) or []
    warnings = details.get("warnings", []) or []

    lines = [
        "✅ Tekshiruv yakunlandi!",
        "",
        f"📊 Umumiy baho: {total_score}/100",
        f"🏷 Daraja: {grade_label}",
        f"🔎 AI ishonchlilik darajasi: {confidence_label}",
        "",
        build_score_table(table_json),
    ]

    if feedback:
        lines.append("")
        lines.append("💬 Qisqa xulosa:")
        for item in feedback[:5]:
            lines.append(f"• {item}")

    if errors:
        lines.append("")
        lines.append("❗ Aniqlangan asosiy kamchiliklar:")
        for item in errors[:5]:
            lines.append(f"• {item}")

    if warnings:
        lines.append("")
        lines.append("⚠️ Ogohlantirishlar:")
        for item in warnings[:5]:
            lines.append(f"• {item}")

    lines.append("")
    lines.append("🖼 Quyida chizmaning overlay natija rasmi yuboriladi.")

    return "\n".join(lines)


async def process_drawing(message: Message, file_id: str, filename: str) -> None:
    filename = safe_filename(filename)

    if not is_allowed_file(filename):
        await message.answer(
            "❌ Bu format qabul qilinmaydi.\n\n"
            "Iltimos, chizmangizni faqat PDF formatda yuboring.\n\n"
            "Hozircha JPG, JPEG va PNG formatlar qabul qilinmaydi, "
            "chunki AI PDF chizmalarni ancha aniqroq tahlil qiladi."
        )
        return

    request_dir = make_request_dir(message)
    result_dir = make_result_dir(message)
    file_path = request_dir / filename

    try:
        await message.answer(
            "✅ PDF chizma qabul qilindi.\n"
            "AI tekshiruv boshlandi. Natija tayyor bo‘lgach, shu yerga yuboraman."
        )

        await bot.send_chat_action(chat_id=message.chat.id, action="typing")

        telegram_file = await bot.get_file(file_id)
        await bot.download_file(telegram_file.file_path, destination=file_path)

        logger.info("PDF fayl yuklandi: %s", file_path)

        result = await asyncio.to_thread(
            evaluate_optional,
            str(file_path),
            str(result_dir),
            ""
        )

        logger.info(
            "AI natija tayyor. Chat ID: %s | Score: %s",
            message.chat.id,
            result.get("total_score")
        )

        result_text = format_result_message(result)
        await send_long_message(message, result_text)

        overlay_path = result.get("overlay_path")

        if overlay_path and Path(overlay_path).exists():
            await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")

            photo = FSInputFile(overlay_path)
            await message.answer_photo(
                photo=photo,
                caption="🖼 Chizmaning overlay natija rasmi"
            )
        else:
            await message.answer(
                "⚠️ AI matnli natijani chiqardi, lekin overlay rasm topilmadi."
            )

    except Exception as e:
        logger.exception("AI ishlov berishda xatolik yuz berdi")

        await message.answer(
            "❌ Chizmaga ishlov berishda xatolik yuz berdi.\n\n"
            "Iltimos, quyidagilarni tekshirib qayta urinib ko‘ring:\n"
            "• fayl PDF formatda bo‘lsin\n"
            "• PDF fayl buzilmagan bo‘lsin\n"
            "• chizma juda xira bo‘lmasin\n\n"
            f"Texnik xatolik: {e}"
        )

    finally:
        cleanup_dir(request_dir)
        cleanup_dir(result_dir)
        logger.info("Temp fayllar tozalandi: %s | %s", request_dir, result_dir)


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Assalomu alaykum!\n\n"
        "Men muhandislik grafikasi chizmalarini AI yordamida tekshiruvchi botman.\n\n"
        "Chizma yuboring, men uni mezonlar bo‘yicha baholab, natijani jadval "
        "va overlay rasm ko‘rinishida qaytaraman.\n\n"
        "❗ Muhim: hozircha faqat PDF formatdagi chizmalar qabul qilinadi.",
        reply_markup=upload_keyboard
    )


@dp.message(F.text == "Chizmani yuklang")
async def upload_button_handler(message: Message) -> None:
    await message.answer(
        "Iltimos, chizmangizni PDF formatda yuboring.\n\n"
        "❗ Hozircha faqat PDF qabul qilinadi.\n"
        "Sabab: PDF formatda AI chizmani ancha aniqroq tahlil qiladi."
    )


@dp.message(F.document)
async def document_handler(message: Message) -> None:
    document = message.document

    if not document:
        await message.answer("Fayl topilmadi. Iltimos, qayta yuboring.")
        return

    filename = document.file_name or "drawing.pdf"
    await process_drawing(message, document.file_id, filename)


@dp.message(F.photo)
async def photo_handler(message: Message) -> None:
    await message.answer(
        "❌ Rasm formatlari hozircha qabul qilinmaydi.\n\n"
        "Iltimos, chizmangizni PDF formatga o‘tkazib, fayl/document sifatida yuboring."
    )


@dp.message()
async def unknown_message_handler(message: Message) -> None:
    await message.answer(
        "Men hozircha faqat PDF formatdagi chizmalarni qabul qilaman.\n\n"
        "Chizma yuborish uchun “Chizmani yuklang” tugmasini bosing."
    )


async def main() -> None:
    logger.info("Bot ishga tushdi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())