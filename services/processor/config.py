"""
Configuration settings for Processor worker service.
"""

from decimal import Decimal
import uuid

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProcessorSettings(BaseSettings):
    """Application settings for Processor detection pipeline worker."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "rt-fads-processor"
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/rt_fads",
        description="Async PostgreSQL connection URL",
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)

    # Redis Messaging
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Streams and Pub/Sub",
    )
    STREAM_TRANSACTIONS: str = Field(default="stream:transactions")
    STREAM_ALERTS: str = Field(default="stream:alerts")
    STREAM_ESCALATIONS: str = Field(default="stream:escalations")
    STREAM_COMPENSATION: str = Field(default="stream:compensation")
    GROUP_TRANSACTIONS: str = Field(default="processor-group")
    GROUP_COMPENSATION: str = Field(default="processor-compensation-group")
    CONSUMER_NAME: str = Field(
        default_factory=lambda: f"processor-worker-{uuid.uuid4().hex[:8]}",
        description="Unique consumer name within consumer group",
    )

    # Stream Polling & Crash Recovery
    CONSUMER_BATCH_SIZE: int = Field(default=10, ge=1, le=500)
    CONSUMER_BLOCK_MS: int = Field(default=2000, ge=0)
    AUTOCLAIM_INTERVAL_SECONDS: float = Field(default=30.0, ge=0.01)
    AUTOCLAIM_MIN_IDLE_TIME_MS: int = Field(default=30000, ge=1)
    MAX_CONSUMER_DELIVERIES: int = Field(default=5, ge=1)

    # Machine Learning Artifacts
    MODEL_PATH: str = Field(default="models/model.pkl")
    MODEL_META_PATH: str = Field(default="models/model_meta.json")

    # Detection Pipeline & Rule Engine
    FRAUD_RULE_REFRESH_SECONDS: float = Field(default=30.0, ge=0.01)
    VELOCITY_WINDOW_MINUTES: int = Field(default=10, ge=1)

    # Composite Scoring & Thresholds
    ALERT_THRESHOLD: Decimal = Field(default=Decimal("0.60"), ge=Decimal("0.0"), le=Decimal("1.0"))
    W_RULE: Decimal = Field(default=Decimal("0.5"), ge=Decimal("0.0"), le=Decimal("1.0"))
    W_ML: Decimal = Field(default=Decimal("0.3"), ge=Decimal("0.0"), le=Decimal("1.0"))
    W_PROFILE: Decimal = Field(default=Decimal("0.2"), ge=Decimal("0.0"), le=Decimal("1.0"))

    # Demo Mode Strategy
    DEMO_MODE: bool = Field(default=False)

    # Escalation Scheduler
    ESCALATION_POLL_SECONDS: float = Field(default=15.0, ge=0.01)
    ESCALATION_EMAIL_MINUTES: float = Field(default=5.0, ge=0.0)
    ESCALATION_SLACK_MINUTES: float = Field(default=10.0, ge=0.0)
    ESCALATION_BATCH_SIZE: int = Field(default=50, ge=1)

    # Telemetry & Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OpenTelemetry Collector gRPC/HTTP endpoint",
    )
    OTEL_ENABLED: bool = Field(default=True)
    PROCESSOR_METRICS_HOST: str = Field(default="0.0.0.0")
    PROCESSOR_METRICS_PORT: int = Field(default=8002)


settings = ProcessorSettings()
