"""
Configuration settings for Outbox Publisher worker service.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutboxPublisherSettings(BaseSettings):
    """Application settings for Outbox Publisher relay worker."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "rt-fads-outbox-publisher"
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rt_fads",
        description="Async PostgreSQL connection URL",
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Streams publication",
    )

    # Polling & Relay Configuration
    POLL_INTERVAL_SECONDS: float = Field(default=0.5, ge=0.01)
    BATCH_SIZE: int = Field(default=50, ge=1, le=500)
    MAX_RETRIES: int = Field(default=8, ge=1, description="Max publish retry attempts before dead-lettering")
    BACKOFF_BASE_SECONDS: float = Field(default=1.0, ge=0.1)
    BACKOFF_MAX_SECONDS: float = Field(default=60.0, ge=1.0)

    # Telemetry & Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OpenTelemetry Collector gRPC/HTTP endpoint",
    )
    OTEL_ENABLED: bool = Field(default=True)
    OUTBOX_METRICS_HOST: str = Field(default="0.0.0.0")
    OUTBOX_METRICS_PORT: int = Field(default=8003)


settings = OutboxPublisherSettings()
