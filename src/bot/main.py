# main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.client.default import DefaultBotProperties
from bot.handlers.register import setup as register_handlers, init_resources, close_resources # Import resource management from handlers
from redis.asyncio import Redis
import os

# Configure logging for main.py
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "your-token")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db/dating")
# RABBITMQ_URL is read inside bot/handlers.py from its own env var or default

async def main():
    # Initialize Redis client and storage
    logger.info("Initializing Redis...")
    redis_client = Redis.from_url(REDIS_URL)
    # Use with_bot_id=True is good for shared Redis
    storage = RedisStorage(redis=redis_client, key_builder=DefaultKeyBuilder(with_bot_id=True))
    logger.info("Redis initialized.")

    # Initialize other resources (RabbitMQ and DB Pool) using the handlers' function
    try:
        await init_resources(database_url=DATABASE_URL)
    except Exception as e:
        logger.error(f"Failed to initialize handlers resources: {e}")
        # Exit if essential resources fail to initialize
        return

    # Initialize Bot and Dispatcher
    dp = Dispatcher(storage=storage, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot = Bot(token=BOT_TOKEN)

    # Register handlers - setup function now just includes the router
    register_handlers(dp)

    # Start polling
    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot)
    finally:
        # Close resources when the bot stops
        logger.info("Bot polling stopped. Closing resources...")
        await close_resources() # Close RabbitMQ and DB Pool
        if redis_client:
            await redis_client.close() # Close Redis
            logger.info("Redis client closed.")
        await bot.session.close()
        logger.info("Bot session closed. Application stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")