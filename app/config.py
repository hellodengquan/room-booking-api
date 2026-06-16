from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "会议室预订系统"
    DATABASE_URL: str = "sqlite:///./room_booking.db"
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MAX_RECURRENCE_DAYS: int = 365
    MAX_ALTERNATIVE_SUGGESTIONS: int = 5


settings = Settings()
