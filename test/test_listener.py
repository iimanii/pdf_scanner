import asyncio
import asyncpg
import os
from dotenv import load_dotenv


async def notification_handler(connection, pid, channel, payload):
    print(f"RECEIVED: channel={channel}, payload={payload}")


async def test_listener():
    load_dotenv()

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    host = "postgres"

    url = f"postgresql://{user}:{password}@{host}:5432/{database}"
    print(f"Connecting to: {url}")

    try:
        conn = await asyncpg.connect(url)
        print("Connected successfully")

        await conn.add_listener('task_updates', notification_handler)
        print("Listening for 'task_updates' notifications...")
        print("Go to pgAdmin and run: SELECT pg_notify('task_updates', '{\"test\": \"hello\"}');")
        print("Press Ctrl+C to stop")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            await conn.close()


if __name__ == "__main__":
    asyncio.run(test_listener())