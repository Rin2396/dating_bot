import asyncio
import os
from aio_pika import connect_robust

RABBIT_URL = os.getenv("RABBIT_URL", "amqp://guest:guest@rabbitmq/")


async def wait_for_rabbitmq(timeout: int = 60, interval: int = 5):
    for attempt in range(0, timeout, interval):
        try:
            connection = await connect_robust(RABBIT_URL)
            print("✅ Connected to RabbitMQ")
            return connection
        except Exception as e:
            print(f"⏳ Waiting for RabbitMQ... ({attempt}s): {e}")
            await asyncio.sleep(interval)
    raise TimeoutError("❌ Failed to connect to RabbitMQ in time.")


async def main():
    connection = await wait_for_rabbitmq()

    print("🚀 Worker is running")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
