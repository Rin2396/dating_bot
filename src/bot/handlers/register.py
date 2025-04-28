from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from bot.states.registration import RegistrationState
import asyncpg
import logging
import aio_pika
import json
import os
import redis.asyncio as redis
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.keyboards.menu import menu_keyboard 
from bot.states.registration import RegistrationState
from bot.handlers import menu
from aiogram.types import BufferedInputFile
from bot.utils.minio_client import upload_photo, get_photo_from_minio

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
    # Здесь должен быть код для удаления анкеты из базы
    await callback.message.answer("Ваша анкета удалена! Чтобы начать регистрацию заново, введите /start.")

@router.callback_query(F.data == "browse_profiles")
async def browse_profiles(callback: CallbackQuery):
    await callback.message.answer("Продолжаем просмотр анкет. Введите /browse")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

rabbitmq_connection: aio_pika.Connection = None
rabbitmq_channel: aio_pika.Channel = None
db_pool: asyncpg.Pool = None
redis_client: redis.Redis = None
profile_queues: dict = {}

router = Router()


def get_swipe_buttons(profile_user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍", callback_data=f"like_{profile_user_id}"),
         InlineKeyboardButton(text="👎", callback_data=f"dislike_{profile_user_id}")]
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


async def init_resources(database_url: str):
    global rabbitmq_connection, rabbitmq_channel, db_pool, redis_client, profile_queues
    logger.info("Initializing resources (RabbitMQ, Redis, DB Pool)...")
    # RabbitMQ
    rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
    rabbitmq_channel = await rabbitmq_connection.channel()
    for name in ('profiles_male', 'profiles_female', 'profiles_all'):
        queue = await rabbitmq_channel.declare_queue(name, durable=True, auto_delete=False)
        profile_queues[name] = queue
    # Redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    db_pool = await asyncpg.create_pool(database_url)
    logger.info("Resources initialized.")

async def close_resources():
    logger.info("Closing resources...")
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed.")
    if rabbitmq_channel:
        await rabbitmq_channel.close()
        logger.info("RabbitMQ channel closed.")
    if rabbitmq_connection:
        await rabbitmq_connection.close()
        logger.info("RabbitMQ connection closed.")
    if redis_client:
        await redis_client.close()
        logger.info("Redis client closed.")
    logger.info("Resources closed.")

def setup(dp: Dispatcher):
    dp.include_router(router)

async def get_and_send_profile(message: Message, gender_filter: str, user_city: str):
    user_id = message.from_user.id

    if not rabbitmq_channel:
        await message.answer("❌ Внутренняя ошибка: RabbitMQ не готов.")
        return

    personal_queue_name = f"user_queue_{user_id}"
    personal_queue = await rabbitmq_channel.declare_queue(personal_queue_name, durable=True, auto_delete=False)
    incoming_msg = await personal_queue.get(no_ack=False, fail=False)

    viewed_key = f"user:{user_id}:viewed_profiles"

    if incoming_msg:
        try:
            profile_data = json.loads(incoming_msg.body.decode('utf-8'))
            target_user_id = profile_data["user_id"]

            already_viewed = await redis_client.sismember(viewed_key, target_user_id)
            if already_viewed:
                await incoming_msg.reject(requeue=False)
                await get_and_send_profile(message, gender_filter, user_city)
                return

            photo_file = await get_photo_from_minio(profile_data["photo_url"])
            if photo_file:
                caption = (
                    f"<b>{profile_data['name']}, {profile_data['age']}</b>\n"
                    f"{profile_data['city']} — {profile_data['description']}\n"
                    f"<i>Ищет:</i> {profile_data['preference']}"
                )
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=get_swipe_buttons(profile_data["user_id"])
                )
                await redis_client.sadd(viewed_key, target_user_id)
                await incoming_msg.ack()
                return
            else:
                await incoming_msg.reject(requeue=False)

        except Exception:
            await incoming_msg.reject(requeue=False)

    queue_name = f'profiles_{gender_filter}'
    queue = profile_queues.get(queue_name)
    if not queue:
        queue = await rabbitmq_channel.declare_queue(queue_name, durable=True, auto_delete=False)
        profile_queues[queue_name] = queue

    while True:
        incoming_msg = await queue.get(no_ack=False, fail=False)
        if incoming_msg is None:
            await message.answer("Пока нет анкет по твоим фильтрам 😢")
            return

        try:
            profile_data = json.loads(incoming_msg.body.decode('utf-8'))
            target_user_id = profile_data["user_id"]

            already_viewed = await redis_client.sismember(viewed_key, target_user_id)
            if already_viewed:
                await incoming_msg.reject(requeue=False)
                continue

            if user_city.lower() != profile_data.get("city", "").lower():
                await incoming_msg.reject(requeue=False)
                continue

            photo_file = await get_photo_from_minio(profile_data["photo_url"])
            if photo_file:
                caption = (
                    f"<b>{profile_data['name']}, {profile_data['age']}</b>\n"
                    f"{profile_data['city']} — {profile_data['description']}\n"
                    f"<i>Ищет:</i> {profile_data['preference']}"
                )
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=get_swipe_buttons(profile_data["user_id"])
                )
                await redis_client.sadd(viewed_key, target_user_id)
                await incoming_msg.ack()
                return
            else:
                await incoming_msg.reject(requeue=False)

        except Exception:
            await incoming_msg.reject(requeue=False)


@router.message(F.text == "/start")
async def start_registration(message: Message, state: FSMContext):
    user_id = message.from_user.id
    logger.info(f"Received /start command from user {user_id}")
    conn = None
    try:
        conn = await db_pool.acquire()
        profile = await conn.fetchrow("SELECT user_id FROM profiles WHERE user_id = $1", user_id)
        if profile:
            await message.answer("Ты уже зарегистрирован(а)! Используй /browse для поиска анкет 💘")
            await state.clear()
            return
        await message.answer("👋 Привет! Давай начнем регистрацию. Как тебя зовут?")
        await state.set_state(RegistrationState.name)
        # Save current FSM state to Redis
        await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.name.state)
    except Exception as e:
        logger.error(f"Database error during /start: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка базы данных при проверке регистрации. Пожалуйста, попробуй позже.")
        await state.clear()
    finally:
        if conn:
            await db_pool.release(conn)

@router.message(RegistrationState.name)
async def get_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(name=message.text)
    await message.answer("Отправь свою фотографию:")
    await state.set_state(RegistrationState.photo)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.photo.state)

@router.message(RegistrationState.photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    photo: PhotoSize = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    photo_url = upload_photo(file_bytes.read())
    await state.update_data(photo_url=photo_url)
    await message.answer("Сколько тебе лет?")
    await state.set_state(RegistrationState.age)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.age.state)

@router.message(RegistrationState.photo, ~F.photo)
async def invalid_photo(message: Message):
    await message.answer("Пожалуйста, отправь фотографию.")


@router.message(RegistrationState.photo, ~F.photo)
async def invalid_photo(message: Message):
    await message.answer("Пожалуйста, отправь фотографию.")

@router.message(RegistrationState.age)
async def get_age(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        age = int(message.text.strip())
        if not 0 < age < 120:
            await message.answer("Пожалуйста, введи корректный возраст (от 1 до 119).")
            return
        await state.update_data(age=age)
        await message.answer("Из какого ты города?")
        await state.set_state(RegistrationState.city)
        await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.city.state)
    except ValueError:
        await message.answer("Пожалуйста, введи возраст числом.")

@router.message(RegistrationState.city)
async def get_city(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(city=message.text)
    await message.answer("Расскажи немного о себе:")
    await state.set_state(RegistrationState.description)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.description.state)

@router.message(RegistrationState.description)
async def get_description(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(description=message.text)
    await message.answer("Кого ты ищешь?")
    await state.set_state(RegistrationState.preference)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.preference.state)

@router.message(RegistrationState.preference)
async def get_preference(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(preference=message.text)
    await message.answer("Укажи свой пол:", reply_markup=get_gender_buttons())
    await state.set_state(RegistrationState.gender)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.gender.state)


@router.callback_query(RegistrationState.gender, F.data.startswith("gender_"))
async def get_gender(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    gender = callback.data.replace("gender_", "")
    await state.update_data(gender=gender)
    await callback.message.answer("Кого ты хочешь видеть в ленте?", reply_markup=get_filter_buttons())
    await state.set_state(RegistrationState.gender_filter)
    await redis_client.hset(f"user:{user_id}", "fsm_state", RegistrationState.gender_filter.state)
    await callback.answer()


@router.callback_query(RegistrationState.gender_filter, F.data.startswith("filter_"))
async def get_filter(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    gender_filter = callback.data.replace("filter_", "")
    await state.update_data(gender_filter=gender_filter)
    await redis_client.hset(f"user:{user_id}", "fsm_state", "registered")
    await redis_client.hset(f"user:{user_id}", "gender_filter", gender_filter)

    data = await state.get_data()
    conn = None
    try:
        conn = await db_pool.acquire()
        await conn.execute(
            """INSERT INTO profiles
               (user_id, name, age, city, description, preference, photo_url, gender, gender_filter, username)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (user_id) DO UPDATE SET
                   name=EXCLUDED.name, age=EXCLUDED.age, city=EXCLUDED.city,
                   description=EXCLUDED.description, preference=EXCLUDED.preference,
                   photo_url=EXCLUDED.photo_url, gender=EXCLUDED.gender,
                   gender_filter=EXCLUDED.gender_filter, username=EXCLUDED.username
            """,
            user_id, data["name"], data["age"], data["city"],
            data["description"], data["preference"], data["photo_url"],
            data["gender"], gender_filter, callback.from_user.username
        )
    finally:
        if conn:
            await db_pool.release(conn)
    await remove_old_profiles(user_id)

    profile_msg = json.dumps({
        "user_id": user_id,
        "name": data["name"],
        "age": data["age"],
        "city": data["city"],
        "description": data["description"],
        "preference": data["preference"],
        "photo_url": data["photo_url"]
    }).encode("utf-8")

    gender_routing_key = "profiles_male" if data["gender"] == "male" else "profiles_female"
    await rabbitmq_channel.default_exchange.publish(
        aio_pika.Message(body=profile_msg),
        routing_key=gender_routing_key
    )
    await rabbitmq_channel.default_exchange.publish(
        aio_pika.Message(body=profile_msg),
        routing_key="profiles_all"
    )

    await redis_client.delete(f"user:{user_id}:current_action")

    caption = (
        f"<b>{data['name']}, {data['age']}</b>\n"
        f"{data['city']} — {data['description']}\n"
        f"<i>Ищет:</i> {data['preference']}"
    )
    photo_file = await get_photo_from_minio(data["photo_url"])
    if photo_file:
        await callback.message.answer_photo(photo=photo_file, caption=caption, parse_mode="HTML")
    else:
        await callback.message.answer("Ошибка загрузки фото анкеты.", parse_mode="HTML")

    await callback.message.answer("✅ Профиль обновлён!\nЧтобы увидеть актуальные анкеты, нажми /browse 💘")
    await state.clear()
    await callback.answer("Анкета сохранена!")


async def remove_old_profiles(user_id: int):
    queues_to_clean = ["profiles_male", "profiles_female", "profiles_all"]

    for queue_name in queues_to_clean:
        queue = profile_queues.get(queue_name)
        if not queue:
            queue = await rabbitmq_channel.declare_queue(queue_name, durable=True, auto_delete=False)
            profile_queues[queue_name] = queue

        new_messages = []

        while True:
            incoming_msg = await queue.get(no_ack=False, fail=False)
            if incoming_msg is None:
                break

            try:
                profile_data = json.loads(incoming_msg.body.decode('utf-8'))
                if profile_data["user_id"] == user_id:
                    await incoming_msg.reject(requeue=False)
                    continue
                else:
                    new_messages.append(incoming_msg)
            except Exception:
                await incoming_msg.reject(requeue=False)

        for msg in new_messages:
            await rabbitmq_channel.default_exchange.publish(
                aio_pika.Message(body=msg.body),
                routing_key=queue_name
            )
            await msg.ack()


@router.message(F.text == "/browse")
async def browse_profiles(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = None
    try:
        conn = await db_pool.acquire()
        user_data = await conn.fetchrow(
            "SELECT gender_filter, city FROM profiles WHERE user_id = $1",
            user_id
        )
        if not user_data:
            await message.answer("Сначала зарегистрируйся через /start 💡")
            await state.clear()
            return

        gender_filter = user_data["gender_filter"]
        user_city = user_data["city"]

        await state.update_data(browse_filter=gender_filter, browse_city=user_city)
        await redis_client.hset(f"user:{user_id}", "current_action", f"browse_{gender_filter}")

    finally:
        if conn:
            await db_pool.release(conn)

    await message.answer("Ищем для тебя анкеты...")

    queue_name = f"user_queue_{user_id}"
    queue = await rabbitmq_channel.declare_queue(queue_name, durable=True, auto_delete=False)
    incoming_msg = await queue.get(no_ack=False, fail=False)

    if incoming_msg:
        try:
            profile_data = json.loads(incoming_msg.body.decode('utf-8'))
            photo_file = await get_photo_from_minio(profile_data["photo_url"])
            if photo_file:
                caption = (
                    f"<b>{profile_data['name']}, {profile_data['age']}</b>\n"
                    f"{profile_data['city']} — {profile_data['description']}\n"
                    f"<i>Ищет:</i> {profile_data['preference']}"
                )
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=get_swipe_buttons(profile_data["user_id"])
                )
                await incoming_msg.ack()
                return
            else:
                await incoming_msg.reject(requeue=False)
        except Exception:
            await incoming_msg.reject(requeue=False)

    data = await state.get_data()
    await get_and_send_profile(message, data["browse_filter"], data["browse_city"])

@router.callback_query(F.data.startswith("like_") | F.data.startswith("dislike_"))
async def handle_swipe(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    action, target_id_str = callback.data.split('_')
    to_user_id = int(target_id_str)

    await redis_client.hset(f"user:{user_id}", mapping={
        "last_action": action,
        "last_target": str(to_user_id)
    })

    await redis_client.sadd(f"user:{user_id}:viewed_profiles", to_user_id)

    conn = None
    try:
        conn = await db_pool.acquire()

        await conn.execute(
            """INSERT INTO likes (from_user_id, to_user_id, is_like)
               VALUES ($1, $2, $3)
               ON CONFLICT (from_user_id, to_user_id)
               DO UPDATE SET is_like=EXCLUDED.is_like, created_at=NOW()
            """, user_id, to_user_id, (action == "like")
        )

        if action == "like":

            profile_from = await conn.fetchrow(
                "SELECT user_id, name, age, city, description, preference, photo_url, gender FROM profiles WHERE user_id = $1",
                user_id
            )

            profile_to = await conn.fetchrow(
                "SELECT gender_filter FROM profiles WHERE user_id = $1",
                to_user_id
            )

            if profile_from and profile_to:
                gender_filter = profile_to["gender_filter"]
                from_gender = profile_from["gender"]
                if (gender_filter == "all" or
                    (gender_filter == "male" and from_gender == "male") or
                    (gender_filter == "female" and from_gender == "female")):

                    profile_msg = json.dumps({
                        "user_id": profile_from["user_id"],
                        "name": profile_from["name"],
                        "age": profile_from["age"],
                        "city": profile_from["city"],
                        "description": profile_from["description"],
                        "preference": profile_from["preference"],
                        "photo_url": profile_from["photo_url"]
                    }).encode("utf-8")

                    queue_name = f"user_queue_{to_user_id}"
                    await rabbitmq_channel.default_exchange.publish(
                        aio_pika.Message(body=profile_msg),
                        routing_key=queue_name
                    )

        if action == "like":
            mutual = await conn.fetchval(
                "SELECT is_like FROM likes WHERE from_user_id=$1 AND to_user_id=$2 AND is_like=TRUE",
                to_user_id, user_id
            )
            if mutual:
                from_rec = await conn.fetchrow("SELECT username FROM profiles WHERE user_id=$1", user_id)
                to_rec = await conn.fetchrow("SELECT username FROM profiles WHERE user_id=$1", to_user_id)
                from_tag = f"@{from_rec['username']}" if from_rec and from_rec.get('username') else f'<a href="tg://user?id={user_id}">Пользователь {user_id}</a>'
                to_tag = f"@{to_rec['username']}" if to_rec and to_rec.get('username') else f'<a href="tg://user?id={to_user_id}">Пользователь {to_user_id}</a>'
                await bot.send_message(user_id, f"💘 У тебя новый мэтч с {to_tag}! Теперь вы можете общаться.", parse_mode="HTML")
                await bot.send_message(to_user_id, f"💘 У тебя новый мэтч с {from_tag}! Теперь вы можете общаться.", parse_mode="HTML")

    finally:
        if conn:
            await db_pool.release(conn)

    await callback.answer("Принято!")

    data = await state.get_data()
    if data.get("browse_filter") and data.get("browse_city"):
        await get_and_send_profile(callback.message, data["browse_filter"], data["browse_city"])
    else:
        await callback.message.answer("Произошла ошибка, попробуйте /browse снова.")


@router.message(F.text == "/reset_browse")
async def reset_browse(message: Message, state: FSMContext):
    user_id = message.from_user.id
    viewed_key = f"user:{user_id}:viewed_profiles"

    await redis_client.delete(viewed_key)

    await message.answer("🔄 Просмотренные анкеты сброшены!\nТеперь ты снова увидишь все доступные анкеты. Нажми /browse 💘")
