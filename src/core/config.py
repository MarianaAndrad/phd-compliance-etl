from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    """Configurações da aplicação, carregadas de variáveis de ambiente ou .env"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )
    # Database - MONGO
    MONGO_HOST: str = "localhost"
    MONGO_PORT: str = "27017"
    DB_MONGO_USERNAME: str = "username"
    DB_MONGO_PASSWORD: str = "password"
    DB_MONGO_NAME: str = "mydatabase"

    DATABASE_URI: str = ""

    @model_validator(mode="after")
    def _build_database_uri(self) -> "Settings":
        if not self.DATABASE_URI:
            self.DATABASE_URI = (
                f"mongodb://{self.DB_MONGO_USERNAME}:{self.DB_MONGO_PASSWORD}"
                f"@{self.MONGO_HOST}:{self.MONGO_PORT}/{self.DB_MONGO_NAME}"
            )
            print(f"Database URI built: {self.DATABASE_URI}")
        return self

    ## Collections
    DB_MONGO_CATALOG_COLLECTION: str = "catalogs"
    DB_MONGO_CONTROL_COLLECTION: str = "controls"

    # LLM
    LLM_BASE_URL: str = "http://localhost:8000/"
    LLM_MODEL: str = "qwen3.5:4b"

settings = Settings()