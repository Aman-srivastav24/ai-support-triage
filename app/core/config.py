from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Support Triage API"
    environment: str = "development"

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
        # --- Gemini (embeddings) ---
    gemini_api_key: str
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
        # --- Groq (generation) ---
    groq_api_key: str
    groq_model: str = "openai/gpt-oss-20b"


@lru_cache
def get_settings() -> Settings:
    return Settings()