from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

menu_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить анкету", callback_data="edit_profile"),
        #    InlineKeyboardButton(text="🗑️ Удалить анкету", callback_data="delete_profile"),
        ],
        [
            InlineKeyboardButton(text="➡️ Продолжить просмотр", callback_data="browse_profiles"),
        ]
    ]
)
