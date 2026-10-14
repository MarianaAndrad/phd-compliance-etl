from core.config import settings

"""MongoDB database"""
from pymongo import AsyncMongoClient

G_MONGODB_CLIENT = None
def get_mongo_client():
    global G_MONGODB_CLIENT

    if not G_MONGODB_CLIENT:
        G_MONGODB_CLIENT = AsyncMongoClient(settings.DATABASE_URI)

    return G_MONGODB_CLIENT

"""Elasticsearch"""
from elasticsearch import Elasticsearch

G_ES_CLIENT = None
def get_elasticsearch_client():
    global G_ES_CLIENT

    if not G_ES_CLIENT:
        G_ES_CLIENT = Elasticsearch(settings.ES_BASE_URL,
                                    basic_auth=(settings.ES_USERNAME, settings.ES_PASSWORD),
                                    verify_certs=False
                                    )

    return G_ES_CLIENT