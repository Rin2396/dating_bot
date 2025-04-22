import json
import asyncpg

DATABASE_URL = "postgresql://user:password@db:5432/dating"

async def process_profile(body: bytes):
    data = json.loads(body)
    user_id = data["user_id"]

    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not user:
            print(f"User {user_id} not found.")
            return

        print(f"🔍 Matching for {user['name']}...")

        # Простой матчинг по полу и возрасту
        matches = await conn.fetch("""
            SELECT * FROM users
            WHERE id != $1
              AND gender = $2
              AND age BETWEEN $3 AND $4
        """, user_id, user["gender_filter"], user["age_filter_from"], user["age_filter_to"])

        print(f"🎯 Found {len(matches)} match(es) for {user['name']}.")
