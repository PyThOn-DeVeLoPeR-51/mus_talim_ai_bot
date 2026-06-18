# Mustaqil Ta'lim AI Telegram Bot

Bu loyiha muhandislik grafikasi chizmalarini Telegram bot orqali AI yordamida tekshirish uchun yaratilgan.

Bot foydalanuvchidan faqat PDF formatdagi chizmani qabul qiladi, chizmani AI orqali baholaydi va natijani quyidagi ko‘rinishda qaytaradi:

- umumiy baho
- baho darajasi
- mezonlar bo‘yicha jadval
- qisqa xulosa
- overlay natija rasmi

## Texnologiyalar

- Python
- Aiogram 3
- OpenCV
- PyMuPDF
- Pillow
- NumPy
- python-dotenv

## Loyiha strukturasi

```text
mus_talim_ai_bot/
├── bot.py
├── optional_mode_v1_backend.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md


## Deploy qilish: Render Background Worker

Bu bot polling orqali ishlaydi. Shuning uchun Render’da Web Service emas, Background Worker sifatida deploy qilish tavsiya qilinadi.

### Render sozlamalari

Service type:

```text
Background Worker

Build Command:
pip install -r requirements.txt

Start Command:
python bot.py

Environment Variables:
BOT_TOKEN=your_real_telegram_bot_token

