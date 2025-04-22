import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.client.default import DefaultBotProperties
from bot.handlers import register_handlers
from redis.asyncio import Redis
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "your-token")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

async def main():
    redis = Redis.from_url(REDIS_URL)
    storage = RedisStorage(redis=redis, key_builder=DefaultKeyBuilder(with_bot_id=True))

    dp = Dispatcher(storage=storage, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot = Bot(token=BOT_TOKEN)

    register_handlers(dp)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
