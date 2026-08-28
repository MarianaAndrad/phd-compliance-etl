from pymongo import AsyncMongoClient

from core.config import settings

MONGODB_CLIENT = None

def get_db_client():
    global MONGODB_CLIENT

    if not MONGODB_CLIENT:
        MONGODB_CLIENT = AsyncMongoClient(settings.DATABASE_URI)

    return MONGODB_CLIENT