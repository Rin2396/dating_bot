# bot/handlers/register.py
from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from bot.states.registration import RegistrationState
import asyncpg
import logging
import aio_pika
import redis.asyncio as redis
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")

rabbitmq_connection: aio_pika.Connection = None
rabbitmq_channel: aio_pika.Channel = None
db_pool: asyncpg.Pool = None

router = Router()

def get_swipe_buttons(profile_user_id: int):
    """Returns inline keyboard buttons for swiping on a profile."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍", callback_data=f"like_{profile_user_id}"),
         InlineKeyboardButton(text="👎", callback_data=f"dislike_{profile_user_id}")]
    ])

def get_gender_buttons():
    """Returns inline keyboard buttons for selecting gender."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мужской", callback_data="gender_male"),
         InlineKeyboardButton(text="Женский", callback_data="gender_female")]
    ])

def get_filter_buttons():
    """Returns inline keyboard buttons for selecting gender filter."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Парней", callback_data="filter_male"),
         InlineKeyboardButton(text="Девушек", callback_data="filter_female"),
         InlineKeyboardButton(text="Всех", callback_data="filter_all")]  
    ])

async def init_resources(database_url: str):
    global rabbitmq_connection, rabbitmq_channel, db_pool
    logger.info("Initializing resources (RabbitMQ, DB Pool)...")
    try:
        rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
        rabbitmq_channel = await rabbitmq_connection.channel()
        await rabbitmq_channel.declare_queue('profiles_male', auto_delete=False, durable=True)
        await rabbitmq_channel.declare_queue('profiles_female', auto_delete=False, durable=True)
        await rabbitmq_channel.declare_queue('profiles_all', auto_delete=False, durable=True)
        logger.info("RabbitMQ initialized and queues declared.")

        db_pool = await asyncpg.create_pool(database_url)
        logger.info("Database pool initialized.")

    except Exception as e:
        logger.error(f"Failed to connect or initialize resources: {e}")
        raise

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
    logger.info("Resources closed.")

def setup(dp: Dispatcher):
    logger.info("Setting up router...")
    dp.include_router(router)
    logger.info("Router included.")

async def get_and_send_profile(message: Message, gender_filter: str):
    if not rabbitmq_channel:
        logger.error("RabbitMQ channel is not initialized.")
        await message.answer("❌ Внутренняя ошибка: RabbitMQ не готов.")
        return

    queue_name = f'profiles_{gender_filter}'
    logger.info(f"Consuming from queue: {queue_name} for user {message.from_user.id}")

    message_obj: aio_pika.IncomingMessage = None
    try:
        message_obj = await rabbitmq_channel.basic_get(queue_name, no_ack=False)
        if message_obj is None:
            await message.answer("Пока нет анкет по твоим фильтрам 😢")
            return

        try:
            profile_data = json.loads(message_obj.body.decode('utf-8'))
            required_keys = ['user_id','name','age','city','description','preference','photo_id']
            if not all(k in profile_data for k in required_keys):
                await message.answer("⚠️ Получены некорректные данные профиля.")
                await message_obj.reject(requeue=False)
                await get_and_send_profile(message, gender_filter)
                return

            caption = (
                f"<b>{profile_data['name']}, {profile_data['age']}</b>\n"
                f"{profile_data['city']} — {profile_data['description']}\n"
                f"<i>Ищет:</i> {profile_data['preference']}"
            )
            await message.answer_photo(
                photo=profile_data["photo_id"],
                caption=caption,
                reply_markup=get_swipe_buttons(profile_data["user_id"]),
                parse_mode="HTML"
            )
            await message_obj.ack()

        except json.JSONDecodeError:
            await message.answer("⚠️ Получены некорректные данные профиля.")
            await message_obj.reject(requeue=False)
            await get_and_send_profile(message, gender_filter)
        except Exception:
            await message.answer("⚠️ Ошибка обработки данных профиля.")
            await message_obj.reject(requeue=False)
            await get_and_send_profile(message, gender_filter)

    except aio_pika.exceptions.AMQPException as e:
        await message.answer(f"⚠️ Ошибка получения анкет из очереди: {e}")
    except Exception as e:
        await message.answer(f"⚠️ Произошла непредвиденная ошибка: {e}")

@router.message(F.text == "/start")
async def start_registration(message: Message, state: FSMContext):
    user_id = message.from_user.id
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
    except Exception:
        await message.answer("⚠️ Ошибка базы данных при проверке регистрации. Попробуй позже.")
        await state.clear()
    finally:
        if conn: await db_pool.release(conn)

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

@router.message(RegistrationState.photo, ~F.photo)
async def invalid_photo(message: Message):
    await message.answer("Пожалуйста, отправь фотографию.")

@router.message(RegistrationState.age)
async def get_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not 0 < age < 120:
            await message.answer("Пожалуйста, введи корректный возраст (от 1 до 119).")
            return
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

@router.callback_query(RegistrationState.gender, F.data.startswith("gender_"))
async def get_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.replace("gender_", "")
    await state.update_data(gender=gender)
    await callback.message.answer("Кого ты хочешь видеть в ленте?", reply_markup=get_filter_buttons())
    await state.set_state(RegistrationState.gender_filter)
    await callback.answer()

@router.callback_query(RegistrationState.gender_filter, F.data.startswith("filter_"))
async def get_filter(callback: CallbackQuery, state: FSMContext):
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
        conn = await db_pool.acquire()
        await conn.execute("""
            INSERT INTO profiles (user_id, name, age, city, description, preference, photo_id, gender, gender_filter, username)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (user_id) DO UPDATE SET
                name=EXCLUDED.name,age=EXCLUDED.age,city=EXCLUDED.city,description=EXCLUDED.description,
                preference=EXCLUDED.preference,photo_id=EXCLUDED.photo_id,gender=EXCLUDED.gender,
                gender_filter=EXCLUDED.gender_filter,username=EXCLUDED.username
        """,callback.from_user.id,data["name"],data["age"],data["city"],data["description"],
            data["preference"],data["photo_id"],data["gender"],gender_filter,callback.from_user.username)
    finally:
        if conn: await db_pool.release(conn)
    await callback.message.answer_photo(photo=data["photo_id"],caption=caption,parse_mode="HTML")
    await callback.message.answer("Анкета готова! Попробуй /browse 💘")
    await state.clear()
    await callback.answer("Анкета сохранена!")

@router.message(F.text == "/browse")
async def browse_profiles(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = None
    try:
        conn = await db_pool.acquire()
        user_data = await conn.fetchrow("SELECT gender_filter FROM profiles WHERE user_id=$1",user_id)
        if not user_data:
            await message.answer("Сначала зарегистрируйся через /start 💡")
            await state.clear()
            return
        await state.update_data(browse_filter=user_data["gender_filter"])
    finally:
        if conn: await db_pool.release(conn)
    await message.answer("Ищем для тебя анкеты...")
    await get_and_send_profile(message, (await state.get_data())["browse_filter"])

@router.callback_query(F.data.startswith("like_")|F.data.startswith("dislike_"))
async def handle_swipe(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    action,to_user_id_str = callback.data.split('_')
    to_user_id = int(to_user_id_str)
    liked = (action=="like")
    conn = None
    try:
        conn = await db_pool.acquire()
        await conn.execute("INSERT INTO likes (from_user_id,to_user_id,is_like) VALUES ($1,$2,$3)"
                           " ON CONFLICT (from_user_id,to_user_id) DO UPDATE SET is_like=EXCLUDED.is_like,created_at=NOW()",
                           callback.from_user.id,to_user_id,liked)
        if liked and await conn.fetchval("SELECT is_like FROM likes WHERE from_user_id=$1 AND to_user_id=$2 AND is_like=TRUE",to_user_id,callback.from_user.id):
            await bot.send_message(callback.from_user.id,f"💘 У тебя новый мэтч!",parse_mode="HTML")
            await bot.send_message(to_user_id,f"💘 У тебя новый мэтч!",parse_mode="HTML")
    finally:
        if conn: await db_pool.release(conn)
    await callback.answer("Принято!")
    await get_and_send_profile(callback.message,(await state.get_data())["browse_filter"])
