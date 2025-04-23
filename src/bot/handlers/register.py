from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from bot.states.registration import RegistrationState
import asyncpg
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()
user_queues = {}


def get_swipe_buttons(profile_user_id: int):
    """Returns inline keyboard buttons for swiping on a profile, including the profile_user_id in callback data."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍", callback_data=f"like_{profile_user_id}"),
         InlineKeyboardButton(text="👎", callback_data=f"dislike_{profile_user_id}")]
    ])

def get_gender_buttons():
    """Returns inline keyboard buttons for selecting gender during registration."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data="gender_male"),
         InlineKeyboardButton(text="Женский", callback_data="gender_female")]
    ])

def get_filter_buttons():
    """Returns inline keyboard buttons for selecting gender filter during registration."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Парней", callback_data="filter_male"),
         InlineKeyboardButton(text="Девушек", callback_data="filter_female"),
         InlineKeyboardButton(text="Всех", callback_data="filter_all")]
    ])


def setup(dp):
    """Includes this router in the main Dispatcher."""
    dp.include_router(router)


@router.message(F.text == "/start")
async def start_registration(message: Message, state: FSMContext):
    """Starts the registration process."""
    await message.answer("👋 Привет! Давай начнем регистрацию. Как тебя зовут?")
    await state.set_state(RegistrationState.name)

@router.message(RegistrationState.name)
async def get_name(message: Message, state: FSMContext):
    """Gets the user's name during registration."""
    await state.update_data(name=message.text)
    await message.answer("Отправь свою фотографию:")
    await state.set_state(RegistrationState.photo)

@router.message(RegistrationState.photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    """Gets the user's photo during registration."""
    photo: PhotoSize = message.photo[-1]
    await state.update_data(photo_id=photo.file_id)
    await message.answer("Сколько тебе лет?")
    await state.set_state(RegistrationState.age)

@router.message(RegistrationState.age)
async def get_age(message: Message, state: FSMContext):
    """Gets the user's age during registration."""
    try:
        age = int(message.text.strip())
        if not 0 < age < 120:
            await message.answer("Пожалуйста, введи корректный возраст.")
            return
        await state.update_data(age=age)
        await message.answer("Из какого ты города?")
        await state.set_state(RegistrationState.city)
    except ValueError:
        await message.answer("Пожалуйста, введи возраст числом.")

@router.message(RegistrationState.city)
async def get_city(message: Message, state: FSMContext):
    """Gets the user's city during registration."""
    await state.update_data(city=message.text)
    await message.answer("Расскажи немного о себе:")
    await state.set_state(RegistrationState.description)

@router.message(RegistrationState.description)
async def get_description(message: Message, state: FSMContext):
    """Gets the user's description during registration."""
    await state.update_data(description=message.text)
    await message.answer("Кого ты ищешь?")
    await state.set_state(RegistrationState.preference)

@router.message(RegistrationState.preference)
async def get_preference(message: Message, state: FSMContext):
    """Gets the user's preference during registration."""
    await state.update_data(preference=message.text)
    await message.answer("Укажи свой пол:", reply_markup=get_gender_buttons())
    await state.set_state(RegistrationState.gender)

@router.callback_query(F.data.startswith("gender_"))
async def get_gender(callback: CallbackQuery, state: FSMContext):
    """Handles gender selection during registration."""
    gender = callback.data.replace("gender_", "")
    await state.update_data(gender=gender)
    await callback.message.answer("Кого ты хочешь видеть в ленте?", reply_markup=get_filter_buttons())
    await state.set_state(RegistrationState.gender_filter)
    await callback.answer()

@router.callback_query(F.data.startswith("filter_"))
async def get_filter(callback: CallbackQuery, state: FSMContext):
    """Handles gender filter selection and saves the user profile."""
    gender_filter = callback.data.replace("filter_", "")
    await state.update_data(gender_filter=gender_filter)
    data = await state.get_data()

    caption = (
        f"<b>{data['name']}, {data['age']}</b>\n"
        f"{data['city']} — {data['description']}\n"
        f"<i>Ищет:</i> {data['preference']}"
    )

    conn = None
    try:
        conn = await asyncpg.connect(user="user", password="password", database="dating", host="db")
        await conn.execute("""
            INSERT INTO profiles (user_id, name, age, city, description, preference, photo_id, gender, gender_filter, username)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, callback.from_user.id, data["name"], data["age"], data["city"],
             data["description"], data["preference"], data["photo_id"], data["gender"], gender_filter, callback.from_user.username)

    except Exception as e:
        logger.error(f"Error saving profile for user {callback.from_user.id}: {e}")
        await callback.message.answer(f"❌ Ошибка сохранения профиля: {e}")
    finally:
        if conn:
            await conn.close()

    await callback.message.answer_photo(photo=data["photo_id"], caption=caption, parse_mode="HTML")
    await callback.message.answer("Анкета готова! Попробуй /browse 💘")
    await state.clear()
    await callback.answer()

@router.message(F.text == "/browse")
async def browse_profiles(message: Message, state: FSMContext):
    """Starts Browse profiles based on user's filter."""
    conn = None
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
            SELECT user_id, name, age, city, description, preference, photo_id, username
            FROM profiles
            WHERE user_id != $1 AND {gender_sql}
            ORDER BY RANDOM()
            LIMIT 10
        """, message.from_user.id)

    except Exception as e:
        logger.error(f"Error Browse profiles for user {message.from_user.id}: {e}")
        await message.answer(f"⚠️ Ошибка: {e}")
        return
    finally:
        if conn:
            await conn.close()

    if not rows:
        await message.answer("Пока нет анкет по твоим фильтрам 😢")
        return

    user_queues[message.from_user.id] = list(rows)
    await send_next_profile(message)

async def send_next_profile(message: Message):
    """Sends the next profile from the user's queue."""
    user_id = message.from_user.id
    queue = user_queues.get(user_id, [])

    if not queue:
        await message.answer("Ты просмотрел(а) все анкеты! 🔁")
        if user_id in user_queues:
            del user_queues[user_id]
        return

    profile = queue.pop(0)
    user_queues[user_id] = queue

    caption = (
        f"<b>{profile['name']}, {profile['age']}</b>\n"
        f"{profile['city']} — {profile['description']}\n"
        f"<i>Ищет:</i> {profile['preference']}"
    )

    try:
        await message.answer_photo(
            photo=profile["photo_id"],
            caption=caption,
            reply_markup=get_swipe_buttons(profile["user_id"]),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error sending profile photo to user {user_id}: {e}")
        await message.answer(f"❌ Ошибка показа анкеты: {e}")


@router.callback_query(F.data.startswith("like_") | F.data.startswith("dislike_"))
async def handle_swipe(callback: CallbackQuery, bot: Bot):
    """Handles like or dislike actions on a profile."""
    user_id = callback.from_user.id


    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Could not edit reply markup for message {callback.message.message_id}: {e}")


    try:
        action, target_user_id_str = callback.data.split('_')
        to_user_id = int(target_user_id_str)
        liked = (action == "like")
    except ValueError:
        logger.error(f"Invalid callback data format: {callback.data} for user {user_id}")
        await callback.answer("Произошла ошибка при обработке свайпа.")
        await send_next_profile(callback.message)
        return

    conn = None
    try:
        conn = await asyncpg.connect(user="user", password="password", database="dating", host="db")

        to_profile_data = await conn.fetchrow("SELECT user_id, name, age, city, description, preference, photo_id, username FROM profiles WHERE user_id = $1", to_user_id)

        if not to_profile_data:
             logger.error(f"Profile data not found for user_id: {to_user_id} (swiped on by {user_id})")
             await callback.answer("Произошла ошибка при обработке свайпа: профиль не найден.")

             await send_next_profile(callback.message)
             return


        await conn.execute("""
            INSERT INTO likes (from_user_id, to_user_id, is_like)
            VALUES ($1, $2, $3)
            ON CONFLICT (from_user_id, to_user_id)
            DO UPDATE SET is_like = EXCLUDED.is_like
        """, user_id, to_user_id, liked)

        existing_like_from_other = await conn.fetchval("""
            SELECT is_like FROM likes
            WHERE from_user_id = $1 AND to_user_id = $2 AND is_like = TRUE
        """, to_user_id, user_id)

        from_user_info = await conn.fetchrow("SELECT username FROM profiles WHERE user_id = $1", user_id)

        from_tag = f"@{from_user_info['username']}" if from_user_info and from_user_info['username'] else f'<a href="tg://user?id={user_id}">Пользователь {user_id}</a>'
        to_tag = f"@{to_profile_data['username']}" if to_profile_data and to_profile_data['username'] else f'<a href="tg://user?id={to_user_id}">Пользователь {to_user_id}</a>'


        if liked and existing_like_from_other:
            logger.info(f"Mutual like between {user_id} and {to_user_id}")
            try:
                await bot.send_message(user_id, f"💘 У тебя новый мэтч с {to_tag}!", parse_mode="HTML")
                await bot.send_message(to_user_id, f"💘 У тебя новый мэтч с {from_tag}!", parse_mode="HTML")
            except Exception as send_e:
                 logger.error(f"Error sending match messages between {user_id} and {to_user_id}: {send_e}")


        elif not liked and existing_like_from_other:
             logger.info(f"User {user_id} disliked user {to_user_id} who previously liked them.")
             try:
                 await bot.send_message(user_id, f"👀 Тебя лайкнул(а) {to_tag}!", parse_mode="HTML")
                 await bot.send_photo(
                     chat_id=user_id,
                     photo=to_profile_data["photo_id"],
                     caption=(
                         f"<b>{to_profile_data['name']}, {to_profile_data['age']}</b>\n"
                         f"{to_profile_data['city']} — {to_profile_data['description']}\n"
                         f"<i>Ищет:</i> {to_profile_data['preference']}"
                     ),
                     parse_mode="HTML"
                 )
             except Exception as send_e:
                 logger.error(f"Error sending 'liked you' message or photo to user {user_id}: {send_e}")


    except Exception as e:
        logger.error(f"Database error in handle_swipe for user {user_id}: {e}")
        await callback.message.answer(f"⚠️ Ошибка базы данных: {e}")
    finally:
        if conn:
            await conn.close()

    await callback.answer("Принято!")
    await send_next_profile(callback.message)
