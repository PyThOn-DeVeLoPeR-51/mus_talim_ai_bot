import asyncio
import logging
import os
import shutil
from pathlib import Path

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


logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
INPUT_DIR = UPLOADS_DIR / "input"
RESULTS_DIR = UPLOADS_DIR / "results"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


upload_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Chizmani yuklang")]
    ],
    resize_keyboard=True
)


def is_allowed_file(filename: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in ALLOWED_EXTENSIONS


def make_request_dir(message: Message) -> Path:
    request_dir = INPUT_DIR / f"{message.chat.id}_{message.message_id}"
    request_dir.mkdir(parents=True, exist_ok=True)
    return request_dir


def make_result_dir(message: Message) -> Path:
    result_dir = RESULTS_DIR / f"{message.chat.id}_{message.message_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir


def cleanup_dir(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def build_score_table(rows: list) -> str:
    if not rows:
        return "Mezonlar jadvali mavjud emas."

    lines = []
    lines.append("Mezonlar bo'yicha natija:")
    lines.append("-" * 55)

    for row in rows:
        criterion = str(row.get("criterion", "Noma'lum mezon"))
        score = int(row.get("score", 0))
        max_score = int(row.get("max_score", 0))
        line = f"{criterion}: {score}/{max_score}"
        lines.append(line)

    return "\n".join(lines)


def format_result_message(result: dict) -> str:
    total_score = int(result.get("total_score", 0))
    details = result.get("details", {}) or {}
    table_json = result.get("table_json", []) or []

    grade_label = details.get("grade_label", "Noma'lum")
    confidence_label = details.get("confidence_label", "unknown")
    feedback = details.get("feedback", []) or []
    warnings = details.get("warnings", []) or []

    lines = [
        "✅ Tekshiruv yakunlandi!",
        "",
        f"Umumiy baho: {total_score}/100",
        f"Baho darajasi: {grade_label}",
        f"Ishonchlilik darajasi: {confidence_label}",
        "",
        build_score_table(table_json),
    ]

    if feedback:
        lines.append("")
        lines.append("Qisqa xulosa:")
        for item in feedback[:5]:
            lines.append(f"- {item}")

    if warnings:
        lines.append("")
        lines.append("Ogohlantirishlar:")
        for item in warnings[:3]:
            lines.append(f"- {item}")

    return "\n".join(lines)


async def process_drawing(message: Message, file_id: str, filename: str):
    if not is_allowed_file(filename):
        await message.answer(
            "Bu format qabul qilinmaydi.\n\n"
            "Faqat PDF, JPG, JPEG yoki PNG formatdagi chizmalarni yuboring."
        )
        return

    await message.answer("Chizma qabul qilindi. AI tekshirmoqda...")

    request_dir = make_request_dir(message)
    result_dir = make_result_dir(message)

    file_path = request_dir / filename

    try:
        telegram_file = await bot.get_file(file_id)
        await bot.download_file(telegram_file.file_path, destination=file_path)

        # AI funksiyasi oddiy sync funksiya, shuning uchun uni alohida thread'da ishlatamiz
        result = await asyncio.to_thread(
            evaluate_optional,
            str(file_path),
            str(result_dir),
            ""
        )

        result_text = format_result_message(result)
        await message.answer(result_text)

        overlay_path = result.get("overlay_path")
        if overlay_path and Path(overlay_path).exists():
            photo = FSInputFile(overlay_path)
            await message.answer_photo(
                photo=photo,
                caption="Chizmaning overlay natija rasmi"
            )
        else:
            await message.answer("Overlay rasm topilmadi.")

    except Exception as e:
        logging.exception("AI ishlov berishda xatolik yuz berdi")
        await message.answer(
            "Chizmaga ishlov berishda xatolik yuz berdi.\n"
            "Iltimos, boshqa chizma bilan qayta urinib ko‘ring.\n\n"
            f"Xatolik: {e}"
        )

    finally:
        cleanup_dir(request_dir)
        cleanup_dir(result_dir)


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Assalomu alaykum!\n\n"
        "Men muhandislik grafikasi chizmasini AI yordamida tekshiruvchi botman.\n\n"
        "Chizmani tekshirtirish uchun quyidagi tugmani bosing.",
        reply_markup=upload_keyboard
    )


@dp.message(F.text == "Chizmani yuklang")
async def upload_button_handler(message: Message):
    await message.answer(
        "Iltimos, chizmangizni PDF, JPG, JPEG yoki PNG formatda yuboring.\n\n"
        "Eslatma: rasmni sifatliroq yuborish uchun uni Telegram’da fayl/document sifatida yuborish yaxshi."
    )


@dp.message(F.document)
async def document_handler(message: Message):
    document = message.document

    if not document:
        await message.answer("Fayl topilmadi. Iltimos, qayta yuboring.")
        return

    filename = document.file_name or "drawing.pdf"
    await process_drawing(message, document.file_id, filename)


@dp.message(F.photo)
async def photo_handler(message: Message):
    photo = message.photo[-1]
    filename = "drawing.jpg"
    await process_drawing(message, photo.file_id, filename)


@dp.message()
async def unknown_message_handler(message: Message):
    await message.answer(
        "Hozircha faqat PDF, JPG, JPEG yoki PNG formatdagi chizmalarni qabul qilaman.\n\n"
        "Chizma yuborish uchun “Chizmani yuklang” tugmasini bosing."
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())