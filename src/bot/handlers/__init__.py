from aiogram import Dispatcher
from bot.handlers import register

def register_handlers(dp: Dispatcher):
    register.setup(dp)
