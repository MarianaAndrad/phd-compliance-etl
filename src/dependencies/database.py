from motor.motor_asyncio import AsyncIOMotorClient

from core.config import settings

async def get_database():
    client = AsyncIOMotorClient(settings.DATABASE_URI)
    try:
        yield client[settings.DB_MONGO_NAME]
    finally:
        client.close()