from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.keyboards.menu import menu_keyboard
from bot.states.registration import RegistrationState

router = Router()

@router.message(F.text == "/menu")
async def show_menu(message: Message):
    await message.answer("Что хотите сделать?", reply_markup=menu_keyboard)

@router.callback_query(F.data == "edit_profile")
async def start_edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Давайте обновим вашу анкету!\nВведите ваше имя:")
    await state.set_state(RegistrationState.name)

@router.callback_query(F.data == "delete_profile")
async def delete_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Ваша анкета удалена! Чтобы начать регистрацию заново, введите /start.")

@router.callback_query(F.data == "browse_profiles")
async def browse_profiles(callback: CallbackQuery):
    await callback.message.answer("Продолжаем просмотр анкет. Введите /browse")
