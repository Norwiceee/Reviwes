
# config.py
"""Configuration module for the Telegram bot.

Загружает переменные окружения из .env и устанавливает глобальные настройки:
токен бота, ID администратора, ID папки Google Drive, ID таблиц Google Sheets.
Также настраивается логирование бота и создаётся экземпляр бота."""
import os
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения из файла .env
load_dotenv()
API_TOKEN = os.getenv("BOT_API_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
SPREADSHEET_ID_1 = os.getenv("SPREADSHEET_ID_1")
SPREADSHEET_ID_2 = os.getenv("SPREADSHEET_ID_2")
SPREADSHEET_ID_3 = os.getenv("SPREADSHEET_ID_3")

# Проверка обязательных переменных
if not API_TOKEN or not ADMIN_ID or not DRIVE_FOLDER_ID or not SPREADSHEET_ID_1 or not SPREADSHEET_ID_2 or not SPREADSHEET_ID_3:
    raise ValueError("Не установлены необходимые переменные окружения в файле .env")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# Создание экземпляра бота с режимом HTML по умолчанию
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
