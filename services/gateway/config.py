"""
Configuration settings for Gateway service.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Application settings for RT-FADS Gateway."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "rt-fads-gateway"
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rt_fads",
        description="Async PostgreSQL / TimescaleDB connection URL",
    )
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for pub/sub and caching",
    )
    STREAM_ALERTS: str = Field(default="stream:alerts")
    STREAM_ESCALATIONS: str = Field(default="stream:escalations")
    GROUP_GATEWAY_NOTIFY: str = Field(default="gateway-notify-group")
    PUBSUB_NOTIFICATIONS: str = Field(default="ws:notifications")
    FORWARDER_BATCH_SIZE: int = Field(default=50, ge=1)
    FORWARDER_BLOCK_MS: int = Field(default=1000, ge=100)
    FORWARDER_AUTOCLAIM_IDLE_MS: int = Field(default=30000, ge=0)
    FORWARDER_AUTOCLAIM_INTERVAL_SECONDS: float = Field(default=30.0, ge=0.0)

    # WebSocket Settings
    WS_PING_INTERVAL_SECONDS: float = Field(default=30.0, ge=0.0)
    WS_PING_TIMEOUT_SECONDS: float = Field(default=10.0, ge=0.0)


    # Security & Rate Limiting
    API_KEY: str = Field(default="rt-fads-default-machine-key")
    JWT_SECRET: str = Field(default="rt-fads-jwt-insecure-secret-key-change-me")
    JWT_ALGORITHM: str = Field(default="HS256")
    RATE_LIMIT_PER_MINUTE: int = Field(default=100, ge=1)

    # Telemetry & Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OpenTelemetry Collector gRPC/HTTP endpoint",
    )
    OTEL_ENABLED: bool = Field(default=True)
    METRICS_ENABLED: bool = Field(default=True)


settings = GatewaySettings()

