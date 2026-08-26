from __future__ import annotations

from dataclasses import dataclass
import os


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

    @classmethod
    def from_environment(cls) -> "Settings":
        raw_secrets = os.getenv("RAZORPAY_WEBHOOK_SECRETS", "")
        secrets = tuple(secret.strip() for secret in raw_secrets.split(",") if secret.strip())
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./recovery.sqlite3"),
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
        )

    def readiness_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.webhook_secrets:
            errors.append("RAZORPAY_WEBHOOK_SECRETS is not configured")
        if self.environment not in {"test", "development", "local"} and not self.internal_api_token:
            errors.append("INTERNAL_API_TOKEN is required outside local/test environments")
        return errors
