# src/bot/main.py
import asyncio
import logging
import os
import redis.asyncio as redis_asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from bot.handlers import register, menu


BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/dating")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Setup Bot and Dispatcher ---
bot = Bot(token=BOT_TOKEN)
# Setup Redis connection for FSM storage
redis_client = redis_asyncio.from_url(REDIS_URL)
storage = RedisStorage(redis=redis_client, key_builder=DefaultKeyBuilder(with_bot_id=True))

dp = Dispatcher(storage=storage)

# Include handlers
register.setup(dp)
dp.include_router(menu.router)

# --- Main startup function ---
async def main() -> None:
    logger.info("Starting bot...")

    try:
        await register.init_resources(DATABASE_URL)
        logger.info("Database pool and RabbitMQ resources initialized.")
    except Exception as e:
        logger.critical(f"Failed to initialize resources: {e}", exc_info=True)
        return

    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Starting bot polling...")
    await dp.start_polling(bot)

# --- Main shutdown function ---
async def on_shutdown() -> None:
    logger.info("Shutting down bot...")

    try:
        await register.close_resources()
        logger.info("Database pool and RabbitMQ resources closed.")
    except Exception as e:
        logger.error(f"Error closing resources: {e}", exc_info=True)

    await storage.close()
    logger.info("Redis storage closed.")

    await bot.session.close()
    logger.info("Bot session closed.")

    logger.info("Bot shut down successfully.")

# --- Entry point ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Bot stopped due to an unhandled exception: {e}", exc_info=True)
    finally:
        asyncio.run(on_shutdown())
