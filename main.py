import os
import logging
import asyncio
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from aiogram.types import BotCommand
# Load environment variables from .env file
load_dotenv()

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Get required environment variables
API_TOKEN = os.getenv("BOT_API_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

if not API_TOKEN or not ADMIN_ID or not DRIVE_FOLDER_ID:
    raise ValueError("Не установлены необходимые переменные окружения (BOT_API_TOKEN, ADMIN_ID, DRIVE_FOLDER_ID).")

# Initialize bot and dispatcher
from aiogram.client.bot import DefaultBotProperties
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Store admin ID and Drive folder ID in bot object for access in handlers
bot.admin_id = ADMIN_ID
bot.drive_folder_id = DRIVE_FOLDER_ID

# Include handlers from other modules
from handlers import auth, reviews
dp.include_router(auth.router)
dp.include_router(reviews.router)

# Import and initialize Google services and database
from google_sheets import init_google_services, import_initial_data, sync_with_google
from database import init_db, is_clients_empty

async def main():
    # Set bot commands for menu (optional)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начало работы"),
        BotCommand(command="stats", description="Просмотр статистики"),
        BotCommand(command="exit", description="Завершить сессию")
    ])
    # Initialize Google Sheets/Drive and database
    init_google_services()
    await init_db()
    # If first run, import data from Google Sheets
    if await is_clients_empty():
        await import_initial_data()
    # Start background synchronization task
    asyncio.create_task(sync_with_google())
    # Start polling updates
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
