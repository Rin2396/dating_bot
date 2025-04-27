# bot/handlers.py
from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, PhotoSize, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
# Remove RedisStorage import here, it's handled in main.py
# from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder # REMOVE THIS
from bot.states.registration import RegistrationState # Assuming this state class exists
import asyncpg
import logging
import aio_pika
import redis.asyncio as redis # Keep redis import if needed elsewhere, though not for storage init here
import json # To parse profile data from RabbitMQ
import os # To potentially read config, though main.py is primary for this

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# Define default URLs, but main.py will pass the actual DB URL
# DATABASE_URL is now passed to init_resources from main.py
# RABBITMQ_URL is used here for the init function
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")

# --- Global Async Resources ---
# Redis resources are managed in main.py and passed via Dispatcher storage
# rabbitmq_connection and rabbitmq_channel will be initialized here
rabbitmq_connection: aio_pika.Connection = None
rabbitmq_channel: aio_pika.Channel = None
db_pool: asyncpg.Pool = None # Use a pool for better DB connection management

router = Router()

# --- Inline Keyboard Buttons ---

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

# --- Async Resource Initialization ---

async def init_resources(database_url: str): # Expect database_url to be passed
    """Initializes RabbitMQ connection/channel and Database pool."""
    global rabbitmq_connection, rabbitmq_channel, db_pool
    logger.info("Initializing resources (RabbitMQ, DB Pool)...")
    try:
        # Initialize RabbitMQ
        rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
        rabbitmq_channel = await rabbitmq_connection.channel()
        # Declare queues (idempotent - safe to call even if they exist)
        await rabbitmq_channel.declare_queue('profiles_male', auto_delete=False, durable=True)
        await rabbitmq_channel.declare_queue('profiles_female', auto_delete=False, durable=True)
        await rabbitmq_channel.declare_queue('profiles_all', auto_delete=False, durable=True)
        logger.info("RabbitMQ initialized and queues declared.")

        # Initialize DB Pool
        db_pool = await asyncpg.create_pool(database_url)
        logger.info("Database pool initialized.")

    except Exception as e:
        logger.error(f"Failed to connect or initialize resources: {e}")
        # Handle this critical error appropriately (e.g., raise exception, exit)
        raise

async def close_resources():
    """Closes RabbitMQ connection and Database pool."""
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

# --- Setup Function ---

# Accept database_url to use the pool managed here
def setup(dp: Dispatcher):
    """Includes this router."""
    logger.info("Setting up router...")
    dp.include_router(router)
    logger.info("Router included.")

# --- Helper to get next profile from RabbitMQ and send ---

async def get_and_send_profile(message: Message, gender_filter: str):
    """
    Consumes one profile from the RabbitMQ queue based on filter
    and sends it to the user. Handles acknowledgment/rejection.
    """
    if not rabbitmq_channel:
        logger.error("RabbitMQ channel is not initialized.")
        await message.answer("❌ Внутренняя ошибка: RabbitMQ не готов.")
        return

    queue_name = f'profiles_{gender_filter}'
    logger.info(f"Attempting to consume from queue: {queue_name} for user {message.from_user.id}")

    message_obj: aio_pika.IncomingMessage = None # Define outside try for access in finally

    try:
        # --- CORRECTED LINE - Confirmed basic_get is used here ---
        message_obj = await rabbitmq_channel.basic_get(queue_name, no_ack=False)
        # --- END CORRECTED LINE ---

        if message_obj is None:
            logger.info(f"Queue {queue_name} is empty for user {message.from_user.id}.")
            await message.answer("Пока нет анкет по твоим фильтрам 😢")
            return

        try:
            # Process/Decode the message body
            profile_data = json.loads(message_obj.body.decode('utf-8'))
            logger.info(f"Consumed profile from RabbitMQ: {profile_data.get('user_id')} for user {message.from_user.id}")

            # Ensure required keys are present
            required_keys = ['user_id', 'name', 'age', 'city', 'description', 'preference', 'photo_id']
            if not all(key in profile_data for key in required_keys):
                 logger.error(f"Received invalid profile data format: {profile_data} from RabbitMQ for user {message.from_user.id}")
                 await message.answer("⚠️ Получены некорректные данные профиля.")
                 if message_obj: # Ensure message_obj exists before rejecting
                      await message_obj.reject(requeue=False) # Reject malformed message
                 await get_and_send_profile(message, gender_filter) # Try fetching the next one
                 return

            caption = (
                f"<b>{profile_data['name']}, {profile_data['age']}</b>\n"
                f"{profile_data['city']} — {profile_data['description']}\n"
                f"<i>Ищет:</i> {profile_data['preference']}"
            )

            # Send the message to the user
            await message.answer_photo(
                photo=profile_data["photo_id"],
                caption=caption,
                reply_markup=get_swipe_buttons(profile_data["user_id"]),
                parse_mode="HTML"
            )
            logger.info(f"Sent profile {profile_data['user_id']} to user {message.from_user.id}")

            # Acknowledge the message ONLY after successful sending
            await message_obj.ack()
            logger.debug(f"Acknowledged message {message_obj.delivery_tag} from queue {queue_name}")


        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from RabbitMQ message: {message_obj.body.decode('utf-8')} for user {message.from_user.id}")
            await message.answer("⚠️ Получены некорректные данные профиля.")
            if message_obj: # Ensure message_obj exists before rejecting
                 await message_obj.reject(requeue=False) # Reject poison messages
            await get_and_send_profile(message, gender_filter) # Try fetching the next one
        except Exception as process_e: # Catch errors during processing or sending
             logger.error(f"Error processing or sending RabbitMQ message for user {message.from_user.id}: {process_e}")
             await message.answer("⚠️ Ошибка обработки данных профиля.")
             if message_obj: # Ensure message_obj exists before rejecting
                  await message_obj.reject(requeue=False) # Reject on processing/sending errors
             await get_and_send_profile(message, gender_filter) # Try fetching the next one


    except aio_pika.exceptions.AMQPException as e:
        logger.error(f"RabbitMQ error while consuming from {queue_name} for user {message.from_user.id}: {e}")
        await message.answer(f"⚠️ Ошибка получения анкет из очереди: {e}")
        # If this outer block catches the error, message_obj was never successfully received,
        # so no need to ack/reject a specific message.
    except Exception as e:
         logger.error(f"Unexpected error in get_and_send_profile for user {message.from_user.id}: {e}")
         await message.answer(f"⚠️ Произошла непредвиденная ошибка: {e}")
         # Same as above, no specific message to ack/reject here.


# --- Registration Handlers (Use DB Pool) ---

@router.message(F.text == "/start")
async def start_registration(message: Message, state: FSMContext):
    """Starts the registration process."""
    user_id = message.from_user.id
    logger.info(f"Received /start command from user {user_id}")

    conn = None
    try:
        logger.debug(f"Attempting to acquire DB connection for user {user_id}")
        conn = await db_pool.acquire() # Use the connection pool
        logger.debug(f"DB connection acquired for user {user_id}")

        logger.debug(f"Checking if user {user_id} is already registered in DB")
        # --- Enhanced Logging Here ---
        profile = await conn.fetchrow("SELECT user_id FROM profiles WHERE user_id = $1", user_id)
        if profile:
            logger.info(f"DB check result for user {user_id}: Profile FOUND.")
            logger.info(f"User {user_id} is already registered. Sending welcome back message.")
            await message.answer("Ты уже зарегистрирован(а)! Используй /browse для поиска анкет 💘")
            await state.clear() # Clear any lingering state if they restart registration
            return
        else:
            logger.info(f"DB check result for user {user_id}: Profile NOT FOUND.")
            logger.info(f"User {user_id} is not registered. Starting registration flow.")
            await message.answer("👋 Привет! Давай начнем регистрацию. Как тебя зовут?")
            await state.set_state(RegistrationState.name)

    except Exception as e:
        logger.error(f"Database error during /start for user {user_id}: {e}", exc_info=True) # Log exception info
        await message.answer("⚠️ Ошибка базы данных при проверке регистрации. Пожалуйста, попробуй позже.")
        # Decide how to handle this error - maybe don't proceed with registration?
        # For now, let's stop if the initial check fails.
        await state.clear() # Clear state on critical error
        return
    finally:
        if conn:
            logger.debug(f"Releasing DB connection for user {user_id}")
            await db_pool.release(conn) # Release the connection back to the pool
            logger.debug(f"DB connection released for user {user_id}")


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

# Add a handler for non-photo messages while in photo state
@router.message(RegistrationState.photo, ~F.photo)
async def invalid_photo(message: Message):
    """Handles messages that are not photos in the photo state."""
    await message.answer("Пожалуйста, отправь фотографию.")


@router.message(RegistrationState.age)
async def get_age(message: Message, state: FSMContext):
    """Gets the user's age during registration."""
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

@router.callback_query(RegistrationState.gender, F.data.startswith("gender_"))
async def get_gender(callback: CallbackQuery, state: FSMContext):
    """Handles gender selection during registration."""
    gender = callback.data.replace("gender_", "")
    await state.update_data(gender=gender)
    await callback.message.answer("Кого ты хочешь видеть в ленте?", reply_markup=get_filter_buttons())
    await state.set_state(RegistrationState.gender_filter)
    await callback.answer()

@router.callback_query(RegistrationState.gender_filter, F.data.startswith("filter_"))
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
        conn = await db_pool.acquire() # Use the connection pool
        await conn.execute("""
            INSERT INTO profiles (user_id, name, age, city, description, preference, photo_id, gender, gender_filter, username)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                age = EXCLUDED.age,
                city = EXCLUDED.city,
                description = EXCLUDED.description,
                preference = EXCLUDED.preference,
                photo_id = EXCLUDED.photo_id,
                gender = EXCLUDED.gender,
                gender_filter = EXCLUDED.gender_filter,
                username = EXCLUDED.username
        """, callback.from_user.id, data["name"], data["age"], data["city"],
             data["description"], data["preference"], data["photo_id"], data["gender"], gender_filter, callback.from_user.username)

    except Exception as e:
        logger.error(f"Error saving profile for user {callback.from_user.id}: {e}")
        await callback.message.answer(f"❌ Ошибка сохранения профиля: {e}")
        # Consider clearing state or setting a specific error state
        await state.clear()
        await callback.answer("Произошла ошибка сохранения.")
        return # Stop processing here on error
    finally:
        if conn:
            await db_pool.release(conn) # Release the connection

    await callback.message.answer_photo(photo=data["photo_id"], caption=caption, parse_mode="HTML")
    await callback.message.answer("Анкета готова! Попробуй /browse 💘")
    await state.clear()
    await callback.answer("Анкета сохранена!")


# --- Browsing Handlers (Use DB Pool and RabbitMQ) ---

@router.message(F.text == "/browse")
async def browse_profiles(message: Message, state: FSMContext):
    """
    Starts browsing profiles. Fetches user's filter from DB pool and gets the
    first profile from the corresponding RabbitMQ queue.
    """
    user_id = message.from_user.id
    conn = None
    gender_filter = None

    try:
        conn = await db_pool.acquire() # Use the connection pool
        user_data = await conn.fetchrow("SELECT gender_filter FROM profiles WHERE user_id = $1", user_id)
        if not user_data:
            await message.answer("Сначала зарегистрируйся через /start 💡")
            await state.clear()
            return

        gender_filter = user_data["gender_filter"]
        await state.update_data(browse_filter=gender_filter) # Store filter in state for swipes

    except Exception as e:
        logger.error(f"Error getting gender_filter for user {user_id}: {e}")
        await message.answer(f"⚠️ Ошибка получения настроек: {e}")
        await state.clear()
        return
    finally:
        if conn:
            await db_pool.release(conn) # Release the connection

    if gender_filter:
        await message.answer("Ищем для тебя анкеты...")
        # get_and_send_profile handles the case where the queue is empty
        await get_and_send_profile(message, gender_filter)
    else:
         # This case should technically not happen if user_data was found but handle defensively
        await message.answer("Не удалось определить твои настройки фильтра.")
        await state.clear()


@router.callback_query(F.data.startswith("like_") | F.data.startswith("dislike_"))
async def handle_swipe(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """Handles like or dislike actions on a profile and fetches the next one."""
    user_id = callback.from_user.id

    # Edit the message to remove buttons immediately
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        logger.debug(f"Removed swipe buttons for message {callback.message.message_id}")
    except Exception as e:
        logger.warning(f"Could not edit reply markup for message {callback.message.message_id}: {e}")
        # Continue processing even if button removal fails

    action = None
    to_user_id = None
    liked = False

    try:
        action, target_user_id_str = callback.data.split('_')
        to_user_id = int(target_user_id_str)
        liked = (action == "like")
        logger.info(f"User {user_id} swiped {action} on user {to_user_id}")
    except ValueError:
        logger.error(f"Invalid callback data format: {callback.data} for user {user_id}")
        await callback.answer("Произошла ошибка при обработке свайпа.")
        # Attempt to send the next profile despite the error
        user_data = await state.get_data()
        gender_filter = user_data.get("browse_filter")
        if gender_filter:
            await get_and_send_profile(callback.message, gender_filter)
        else:
             await callback.message.answer("Не удалось загрузить следующую анкету.")
        return

    conn = None
    try:
        conn = await db_pool.acquire() # Use the connection pool

        # Fetch target user's profile data for potential match notification
        to_profile_data = await conn.fetchrow("SELECT user_id, name, age, city, description, preference, photo_id, username FROM profiles WHERE user_id = $1", to_user_id)
        if not to_profile_data:
             logger.error(f"Profile data not found for user_id: {to_user_id} (swiped on by {user_id})")
             await callback.answer("Произошла ошибка при обработке свайпа: профиль не найден.")
             # Attempt to send the next profile
             user_data = await state.get_data()
             gender_filter = user_data.get("browse_filter")
             if gender_filter:
                 await get_and_send_profile(callback.message, gender_filter)
             else:
                  await callback.message.answer("Не удалось загрузить следующую анкету.")
             return


        # Record the like/dislike
        await conn.execute("""
            INSERT INTO likes (from_user_id, to_user_id, is_like)
            VALUES ($1, $2, $3)
            ON CONFLICT (from_user_id, to_user_id)
            DO UPDATE SET is_like = EXCLUDED.is_like, created_at = NOW() -- Optional: update timestamp
        """, user_id, to_user_id, liked)
        logger.info(f"Recorded swipe: user {user_id} -> user {to_user_id}, liked={liked}")


        # Check for mutual like (match) only if the current action is 'like'
        if liked:
            existing_like_from_other = await conn.fetchval("""
                SELECT is_like FROM likes
                WHERE from_user_id = $1 AND to_user_id = $2 AND is_like = TRUE
            """, to_user_id, user_id)

            if existing_like_from_other:
                logger.info(f"Mutual like detected between {user_id} and {to_user_id}")
                # Fetch current user's username for the notification message
                from_user_info = await conn.fetchrow("SELECT username FROM profiles WHERE user_id = $1", user_id)

                from_tag = f"@{from_user_info['username']}" if from_user_info and from_user_info['username'] else f'<a href="tg://user?id={user_id}">Пользователь {user_id}</a>'
                to_tag = f"@{to_profile_data['username']}" if to_profile_data and to_profile_data['username'] else f'<a href="tg://user?id={to_user_id}">Пользователь {to_user_id}</a>'

                try:
                    await bot.send_message(user_id, f"💘 У тебя новый мэтч с {to_tag}! Теперь вы можете общаться.", parse_mode="HTML")
                    await bot.send_message(to_user_id, f"💘 У тебя новый мэтch с {from_tag}! Теперь вы можете общаться.", parse_mode="HTML")
                    logger.info(f"Sent match notifications to {user_id} and {to_user_id}")
                except Exception as send_e:
                    logger.error(f"Error sending match messages between {user_id} and {to_user_id}: {send_e}")

        # Optional: Notify the *other* user if they were liked (even without mutual like)
        # elif liked: # This block is for non-mutual likes that should notify the other user
        #    existing_dislike_from_other = await conn.fetchval("SELECT is_like FROM likes WHERE from_user_id = $1 AND to_user_id = $2 AND is_like = FALSE", to_user_id, user_id)
        #    if existing_dislike_from_other is None: # Only notify if they haven't explicitly disliked you back
        #         try:
        #              from_user_info = await conn.fetchrow("SELECT username FROM profiles WHERE user_id = $1", user_id)
        #              from_tag = f"@{from_user_info['username']}" if from_user_info and from_user_info['username'] else f'<a href="tg://user?id={user_id}">Пользователь {user_id}</a>'
        #              await bot.send_message(to_user_id, f"🔔 Тебя лайкнул(а) {from_tag}! Проверь анкету в ленте.", parse_mode="HTML")
        #              logger.info(f"Sent 'liked you' notification to {to_user_id} from {user_id}")
        #         except Exception as send_e:
        #              logger.error(f"Error sending 'liked you' message to {to_user_id}: {send_e}")


    except Exception as e:
        logger.error(f"Database error in handle_swipe for user {user_id}: {e}")
        await callback.message.answer(f"⚠️ Ошибка базы данных: {e}")
        # Attempt to send the next profile despite the DB error
        user_data = await state.get_data()
        gender_filter = user_data.get("browse_filter")
        if gender_filter:
            await get_and_send_profile(callback.message, gender_filter)
        else:
             await callback.message.answer("Не удалось загрузить следующую анкету.")
        await callback.answer("Произошла ошибка.")
        return # Stop processing here on DB error
    finally:
        if conn:
            await db_pool.release(conn) # Release the connection

    # Get the user's filter from state to fetch the next profile
    user_data = await state.get_data()
    gender_filter = user_data.get("browse_filter")

    if gender_filter:
        await callback.answer("Принято!") # Acknowledge callback only after DB ops
        await get_and_send_profile(callback.message, gender_filter)
    else:
         logger.warning(f"Browse filter not found in state for user {user_id} after swipe.")
         await callback.answer("Принято, но не удалось загрузить следующую анкету (фильтр потерян).")
         await callback.message.answer("Произошла ошибка, попробуйте /browse снова.")
         await state.clear() # Clear state if filter is missing

