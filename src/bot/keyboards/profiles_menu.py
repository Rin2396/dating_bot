from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

profiles_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="👍 Лайк", callback_data="like"),
            InlineKeyboardButton(text="👎 Дизлайк", callback_data="dislike"),
        ],
        [
            InlineKeyboardButton(text="⏩ Пропустить", callback_data="skip"),
        ]
    ]
)
