from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from bot.states.registration import RegistrationState
import asyncpg

router = Router()
user_queues = {}

def get_swipe_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍", callback_data="like"),
         InlineKeyboardButton(text="👎", callback_data="dislike")]
    ])

def get_gender_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data="gender_male"),
         InlineKeyboardButton(text="Женский", callback_data="gender_female")]
    ])

def get_filter_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Парней", callback_data="filter_male"),
         InlineKeyboardButton(text="Девушек", callback_data="filter_female"),
         InlineKeyboardButton(text="Всех", callback_data="filter_all")]
    ])

def setup(dp):
    dp.include_router(router)

@router.message(F.text == "/start")
async def start_registration(message: Message, state: FSMContext):
    await message.answer("👋 Привет! Давай начнем регистрацию. Как тебя зовут?")
    await state.set_state(RegistrationState.name)

@router.message(RegistrationState.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отправь свою фотографию:")
    await state.set_state(RegistrationState.photo)

@router.message(RegistrationState.photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    photo: PhotoSize = message.photo[-1]
    await state.update_data(photo_id=photo.file_id)
    await message.answer("Сколько тебе лет?")
    await state.set_state(RegistrationState.age)

@router.message(RegistrationState.age)
async def get_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        await state.update_data(age=age)
        await message.answer("Из какого ты города?")
        await state.set_state(RegistrationState.city)
    except ValueError:
        await message.answer("Пожалуйста, введи возраст числом.")

@router.message(RegistrationState.city)
async def get_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text)
    await message.answer("Расскажи немного о себе:")
    await state.set_state(RegistrationState.description)

@router.message(RegistrationState.description)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Кого ты ищешь?")
    await state.set_state(RegistrationState.preference)

@router.message(RegistrationState.preference)
async def get_preference(message: Message, state: FSMContext):
    await state.update_data(preference=message.text)
    await message.answer("Укажи свой пол:", reply_markup=get_gender_buttons())
    await state.set_state(RegistrationState.gender)

@router.callback_query(F.data.startswith("gender_"))
async def get_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("gender_", "")
    await state.update_data(gender=gender)
    await callback.message.answer("Кого ты хочешь видеть в ленте?", reply_markup=get_filter_buttons())
    await state.set_state(RegistrationState.gender_filter)
    await callback.answer()

@router.callback_query(F.data.startswith("filter_"))
async def get_filter(callback: CallbackQuery, state: FSMContext):
    gender_filter = callback.data.replace("filter_", "")
    await state.update_data(gender_filter=gender_filter)
    data = await state.get_data()

    caption = (
        f"<b>{data['name']}, {data['age']}</b>\n"
        f"{data['city']} — {data['description']}\n"
        f"<i>Ищет:</i> {data['preference']}"
    )

    try:
        conn = await asyncpg.connect(user="user", password="password", database="dating", host="db")
        await conn.execute("""
            INSERT INTO profiles (user_id, name, age, city, description, preference, photo_id, gender, gender_filter)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, callback.from_user.id, data["name"], data["age"], data["city"],
             data["description"], data["preference"], data["photo_id"], data["gender"], gender_filter)
        await conn.close()
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка сохранения профиля: {e}")
        return

    await callback.message.answer_photo(photo=data["photo_id"], caption=caption, parse_mode="HTML")
    await callback.message.answer("Анкета готова! Попробуй /browse 💘")
    await state.clear()
    await callback.answer()

@router.message(F.text == "/browse")
async def browse_profiles(message: Message, state: FSMContext):
    try:
        conn = await asyncpg.connect(user="user", password="password", database="dating", host="db")
        user_data = await conn.fetchrow("SELECT gender_filter FROM profiles WHERE user_id = $1", message.from_user.id)
        if not user_data:
            await message.answer("Сначала зарегистрируйся через /start 💡")
            return

        gender_filter = user_data["gender_filter"]
        gender_sql = {
            "male": "gender = 'male'",
            "female": "gender = 'female'",
            "all": "TRUE"
        }[gender_filter]

        rows = await conn.fetch(f"""
            SELECT user_id, name, age, city, description, preference, photo_id
            FROM profiles
            WHERE user_id != $1 AND {gender_sql}
            ORDER BY RANDOM()
            LIMIT 10
        """, message.from_user.id)

        await conn.close()
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {e}")
        return

    if not rows:
        await message.answer("Пока нет анкет по твоим фильтрам 😢")
        return

    user_queues[message.from_user.id] = rows
    await send_next_profile(message)

async def send_next_profile(message: Message):
    queue = user_queues.get(message.from_user.id, [])
    if not queue:
        await message.answer("Ты просмотрел(а) все анкеты! 🔁")
        return

    profile = queue.pop(0)
    user_queues[message.from_user.id] = queue

    caption = (
        f"<b>{profile['name']}, {profile['age']}</b>\n"
        f"{profile['city']} — {profile['description']}\n"
        f"<i>Ищет:</i> {profile['preference']}"
    )

    try:
        await message.answer_photo(
            photo=profile["photo_id"],
            caption=caption,
            reply_markup=get_swipe_buttons(),
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка показа анкеты: {e}")

@router.callback_query(F.data.in_({"like", "dislike"}))
async def handle_swipe(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    queue = user_queues.get(user_id, [])

    if not queue:
        await callback.message.edit_reply_markup()
        await callback.message.answer("Ты просмотрел(а) все анкеты! 🔁")
        return

    profile = queue.pop(0)
    user_queues[user_id] = queue
    liked = callback.data == "like"
    to_user_id = profile["user_id"]

    try:
        conn = await asyncpg.connect(user="user", password="password", database="dating", host="db")

        # Сохраняем свайп
        await conn.execute("""
            INSERT INTO likes (from_user_id, to_user_id, is_like)
            VALUES ($1, $2, $3)
            ON CONFLICT (from_user_id, to_user_id)
            DO UPDATE SET is_like = EXCLUDED.is_like
        """, user_id, to_user_id, liked)

        # Узнаём, как ранее проголосовал он
        existing_like = await conn.fetchval("""
            SELECT is_like FROM likes
            WHERE from_user_id = $1 AND to_user_id = $2
        """, to_user_id, user_id)

        from_tag = f"@{callback.from_user.username}" if callback.from_user.username else f"id{user_id}"
        to_tag = f"@{profile.get('username')}" if profile.get("username") else f"id{to_user_id}"

        # === 💘 Взаимный лайк ===
        if liked and existing_like:
            await bot.send_message(user_id, f"💘 У тебя новый мэтч с {to_tag}!")
            await bot.send_message(to_user_id, f"💘 У тебя новый мэтч с {from_tag}!")

        # === 👀 Тебя лайкнули первым ===
        elif existing_like and existing_like is True and not liked:
            await bot.send_message(user_id, f"👀 Тебя лайкнул(а) {to_tag}!")
            await bot.send_photo(
                chat_id=user_id,
                photo=profile["photo_id"],
                caption=(
                    f"<b>{profile['name']}, {profile['age']}</b>\n"
                    f"{profile['city']} — {profile['description']}\n"
                    f"<i>Ищет:</i> {profile['preference']}"
                ),
                parse_mode="HTML"
            )

        await conn.close()

    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка базы данных: {e}")

    await callback.answer("Принято!")
    await send_next_profile(callback.message)
