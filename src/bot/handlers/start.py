# src/bot/handlers/start.py
from aiogram import types
from aiogram.filters import Command
from bot import dp

@dp.message(Command(commands=["start"]))
async def cmd_start(message: types.Message):
    await message.answer("✅ Bot is alive and polling!")
