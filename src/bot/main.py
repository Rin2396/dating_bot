# src/bot/main.py
import asyncio
import logging
import os
import redis

# Import Bot and Dispatcher
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton # Убираем BotProperties из импорта types
from aiogram.enums import ParseMode # ParseMode все еще может быть доступен, или нужно импортировать из aiogram.types
# В старых версиях Aiogram ParseMode часто был в aiogram.types
# Если ParseMode.HTML вызывает ошибку, попробуйте from aiogram.types import ParseMode
# from aiogram.types import ParseMode # Раскомментируйте эту строку, если ParseMode.HTML вызывает ошибку
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder

# Import the setup and resource management functions from your handlers
from bot.handlers import register # Assuming register handlers are in bot/handlers/register.py
from bot.handlers import profiles_menu # Assuming menu handlers are in bot/handlers/profiles_menu.py

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/dating") # Get DB URL from env

# --- Bot and Dispatcher Setup ---
# В старых версиях Aiogram parse_mode передается напрямую в конструктор Bot
# Убираем default=BotProperties(...)
bot = Bot(token=BOT_TOKEN)


# Setup Redis Storage for FSM
# Use DefaultKeyBuilder with bot_id to avoid conflicts if running multiple bots
redis_client = redis.asyncio.from_url(REDIS_URL)
# В старых версиях DefaultKeyBuilder может не существовать или быть в другом месте
# Если DefaultKeyBuilder вызывает ошибку, возможно, вам не нужен key_builder или нужен другой подход
storage = RedisStorage(redis=redis_client, key_builder=DefaultKeyBuilder(with_bot_id=True))
# Если DefaultKeyBuilder вызывает ошибку, попробуйте:
# storage = RedisStorage(redis=redis_client)


dp = Dispatcher(storage=storage)

# --- Register Handlers ---
# Include routers from your handler modules
register.setup(dp) # Assuming setup function in register.py includes its router
profiles_menu.setup(dp) # Assuming setup function in profiles_menu.py includes its router


# --- Main startup function ---
async def main() -> None:
    logger.info("Starting bot...")

    # Initialize database pool and RabbitMQ resources
    # This must be called BEFORE starting the bot polling
    try:
        await register.init_resources(DATABASE_URL) # Pass DATABASE_URL
        logger.info("Database pool and RabbitMQ resources initialized.")
    except Exception as e:
        logger.critical(f"Failed to initialize resources: {e}", exc_info=True)
        # Exit or handle the critical error appropriately
        return # Stop execution if resources fail to initialize


    # Drop pending updates
    # В старых версиях Aiogram delete_webhook может не принимать drop_pending_updates
    # Если эта строка вызывает ошибку, попробуйте: await bot.delete_webhook()
    await bot.delete_webhook(drop_pending_updates=True)


    # Start polling for updates
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


# --- Main shutdown function ---
async def on_shutdown() -> None:
    logger.info("Shutting down bot...")

    # Close database pool and RabbitMQ resources
    try:
        await register.close_resources()
        logger.info("Database pool and RabbitMQ resources closed.")
    except Exception as e:
        logger.error(f"Error closing resources: {e}", exc_info=True)

    # Close Redis connection
    await storage.close()
    logger.info("Redis storage closed.")

    # Close bot session
    await bot.session.close()
    logger.info("Bot session closed.")

    logger.info("Bot shut down successfully.")


if __name__ == "__main__":
    # Run the main function and handle shutdown
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Bot stopped due to an unhandled exception: {e}", exc_info=True)
    finally:
        # Ensure shutdown tasks are run even if main() exits due to error
        asyncio.run(on_shutdown())

