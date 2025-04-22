from aiogram.fsm.state import State, StatesGroup

class RegistrationState(StatesGroup):
    name = State()
    photo = State()
    age = State()
    city = State()
    description = State()
    preference = State()
    age_filter = State()
    gender = State()
    gender_filter = State()
