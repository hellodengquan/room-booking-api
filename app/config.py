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
    MAX_ALTERNATIVE_SUGGESTIONS: int = 10
    DEFAULT_TIMEZONE: str = "Asia/Shanghai"
    MAX_CANCELLATION_BATCH_SIZE: int = 100
    DELEGATION_DEFAULT_DURATION_DAYS: int = 30
    SUGGESTION_SCORE_WEIGHT_TIME: float = 0.4
    SUGGESTION_SCORE_WEIGHT_ROOM: float = 0.3
    SUGGESTION_SCORE_WEIGHT_DEVICE: float = 0.3
    SUGGESTION_SCORE_LEVEL_EXCELLENT: float = 0.85
    SUGGESTION_SCORE_LEVEL_GOOD: float = 0.7
    SUGGESTION_SCORE_LEVEL_FAIR: float = 0.5
    DEVICE_MATCH_WEIGHT_PER_DEVICE: float = 0.1
    CANCELLATION_AUDIT_RETENTION_DAYS: int = 90
    CANCELLATION_APPROVAL_TIMEOUT_HOURS: int = 48
    CANCELLATION_APPROVAL_TIMEOUT_ACTION: str = "reject"
    COVERAGE_SLA_TARGET: float = 75.0
    ENABLE_DST_HANDLING: bool = True
    DEVICE_BONUS_CAP_ENABLED: bool = True
    DEVICE_BONUS_BASE_CAP: float = 0.3
    DEVICE_BONUS_CAP_PER_DEVICE: float = 0.05
    DEVICE_BONUS_MAX_CAP: float = 0.6
    DST_NOTIFICATION_ENABLED: bool = True
    DST_NOTIFICATION_DAYS_BEFORE: int = 7
    DELEGATION_AUDIT_ENABLED: bool = True
    AB_TEST_ENABLED: bool = False
    AB_TEST_DEFAULT_VARIANT: str = "control"
    CALIBRATION_SAMPLE_ENABLED: bool = True
    CANCELLATION_AUDIT_SNAPSHOT_RETENTION_DAYS: int = 365
    COVERAGE_SLA_MODULES: str = "services:85,routers:70,models:90,schemas:80"
    ADVANCED_PERMISSION_STRICT: bool = True
    AB_TEST_MIN_SAMPLE_SIZE: int = 30
    AB_TEST_CONFIDENCE_LEVEL: float = 0.95
    TENANT_CONFIG_CACHE_TTL_SECONDS: int = 300
    CALIBRATION_OUTLIER_METHOD: str = "iqr"
    CALIBRATION_OUTLIER_THRESHOLD: float = 1.5
    SNAPSHOT_RETENTION_WINDOW_DAYS: str = "30,90,365"
    COVERAGE_SLA_ALERT_CHANNEL: str = "log"
    COVERAGE_SLA_WEBHOOK_URL: str = ""
    DEVICE_BONUS_PUSH_STRATEGY: str = "on_change"
    COVERAGE_DASHBOARD_ENABLED: bool = True


settings = Settings()
