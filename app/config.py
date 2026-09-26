from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kbagent:kbagent@localhost:5433/kbagent"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "openai/gpt-oss-120b"
    groq_api_key: str = ""
    llm_provider: str = "groq"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    chunk_size: int = 500
    chunk_overlap: int = 80
    top_k: int = 5


settings = Settings()
