from __future__ import annotations

from dataclasses import dataclass
import os


from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    webhook_secrets: tuple[str, ...]
    environment: str
    max_webhook_bytes: int
    processing_timeout_seconds: int = 15 * 60
    redis_claim_idle_ms: int = 60_000
    internal_api_token: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_api_base_url: str = "https://api.razorpay.com/v1"
    reconciliation_timeout_seconds: float = 5.0
    openai_api_key: str | None = None
    stage3_sweep_interval_seconds: int = 5
    stage3_min_net_improvement_threshold: float = 10.0
    stage3_max_allowed_rate_degradation: float = 0.0
    stage3_min_action_sample_size: int = 10
    stage3_max_projection_age_hours: int = 72

    @classmethod
    def from_environment(cls, allow_sqlite: bool = False) -> "Settings":
        load_dotenv()
        raw_db_url = os.getenv("DATABASE_URL")
        if not raw_db_url or not raw_db_url.strip():
            raise ValueError(
                "DATABASE_URL environment variable is required. "
                "Application runtime requires a valid PostgreSQL database connection URI."
            )
        db_url = raw_db_url.strip()
        if not allow_sqlite:
            if db_url.startswith("sqlite") or "sqlite" in db_url.lower():
                raise ValueError(
                    "SQLite database URL is rejected for application runtime. "
                    "DATABASE_URL must be a valid PostgreSQL connection URI (e.g. postgresql+psycopg://...)."
                )
            if not (db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://") or db_url.startswith("postgres://")):
                raise ValueError(
                    f"Unsupported DATABASE_URL scheme '{db_url.split('://')[0] if '://' in db_url else db_url}'. "
                    "Application runtime requires PostgreSQL."
                )
        raw_secrets = os.getenv("RAZORPAY_WEBHOOK_SECRETS", "")
        secrets = tuple(secret.strip() for secret in raw_secrets.split(",") if secret.strip())
        return cls(
            database_url=db_url,
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            webhook_secrets=secrets,
            environment=os.getenv("APP_ENVIRONMENT", "test"),
            max_webhook_bytes=int(os.getenv("MAX_WEBHOOK_BYTES", "1048576")),
            processing_timeout_seconds=int(os.getenv("PROCESSING_TIMEOUT_SECONDS", "900")),
            redis_claim_idle_ms=int(os.getenv("REDIS_CLAIM_IDLE_MS", "60000")),
            internal_api_token=os.getenv("INTERNAL_API_TOKEN") or None,
            razorpay_key_id=os.getenv("RAZORPAY_KEY_ID") or None,
            razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET") or None,
            razorpay_api_base_url=os.getenv("RAZORPAY_API_BASE_URL", "https://api.razorpay.com/v1").rstrip("/"),
            reconciliation_timeout_seconds=float(os.getenv("RECONCILIATION_TIMEOUT_SECONDS", "5")),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            stage3_sweep_interval_seconds=int(os.getenv("STAGE3_SWEEP_INTERVAL_SECONDS", "5")),
            stage3_min_net_improvement_threshold=float(os.getenv("STAGE3_MIN_NET_IMPROVEMENT_THRESHOLD", "10.0")),
            stage3_max_allowed_rate_degradation=float(os.getenv("STAGE3_MAX_ALLOWED_RATE_DEGRADATION", "0.0")),
            stage3_min_action_sample_size=int(os.getenv("STAGE3_MIN_ACTION_SAMPLE_SIZE", "10")),
            stage3_max_projection_age_hours=int(os.getenv("STAGE3_MAX_PROJECTION_AGE_HOURS", "72")),
        )

    def readiness_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.webhook_secrets:
            errors.append("RAZORPAY_WEBHOOK_SECRETS is not configured")
        if self.environment not in {"test", "development", "local"} and not self.internal_api_token:
            errors.append("INTERNAL_API_TOKEN is required outside local/test environments")
        if not (self.database_url.startswith("postgresql://") or self.database_url.startswith("postgresql+psycopg://") or self.database_url.startswith("postgres://")):
            errors.append("Application runtime requires a valid PostgreSQL DATABASE_URL")
        return errors
