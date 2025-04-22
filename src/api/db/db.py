import asyncpg
from api.models.user_model import User

DATABASE_URL = "postgresql://user:password@db:5432/dating"

class UserDB:
    pool = None

    @classmethod
    async def init(cls):
        cls.pool = await asyncpg.create_pool(DATABASE_URL)

    @classmethod
    async def create_user(cls, user_id: str, user: User):
        async with cls.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, name, photo_url, age, city, description, age_filter_from, age_filter_to, gender, gender_filter)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """, user_id, user.name, user.photo_url, user.age, user.city, user.description,
                 user.age_filter[0], user.age_filter[1], user.gender, user.gender_filter)

async def init_db():
    await UserDB.init()
