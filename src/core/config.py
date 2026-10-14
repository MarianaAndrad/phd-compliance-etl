from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    """Application settings, loaded through an .env file or environment variables"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )
    
    # MongoDB
    MONGO_HOST: str = "localhost"
    MONGO_PORT: str = "27017"
    DB_MONGO_USERNAME: str = ""
    DB_MONGO_PASSWORD: str = ""
    DB_MONGO_NAME: str = "test"

    DATABASE_URI: str = ""

    @model_validator(mode="after")
    def _build_database_uri(self) -> "Settings":
        if not self.DATABASE_URI:
            self.DATABASE_URI = (
                f"mongodb://{self.DB_MONGO_USERNAME}:{self.DB_MONGO_PASSWORD}"
                f"@{self.MONGO_HOST}:{self.MONGO_PORT}/{self.DB_MONGO_NAME}"
            )
            print(f"[INFO] Database URI built: {self.DATABASE_URI}")
        return self

    ## MongoDB collections
    DB_MONGO_CATALOG_COLLECTION: str = "catalogs"
    DB_MONGO_CONTROL_COLLECTION: str = "controls"

    # LLM
    LLM_BASE_URL: str = "http://localhost:8000/"
    LLM_MODEL: str = "qwen3.5:4b"

    # Elasticsearch
    ES_BASE_URL: str = "http://localhost:9200"
    ES_USERNAME: str = ""
    ES_PASSWORD: str = ""

settings = Settings()