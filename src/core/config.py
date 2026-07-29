"""Application settings"""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Configurações da aplicação, carregadas de variáveis de ambiente ou .env"""

    # Mongo
    DATABASE_URI: str = "mongodb://admin:senha123@mongo:27017/?authSource=admin"
    DATABASE_NAME: str = "meu_banco"

    # Collections
    CATALOG_COLLECTION: str = "catalogs"
    CONTROL_COLLECTION: str = "controls"

    # LLM
    LLM_BASE_URL: str = "http://localhost:8000/"
    LLM_MODEL: str = "qwen3.5:4b"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

settings = Settings()