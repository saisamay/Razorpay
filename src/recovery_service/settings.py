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
        )

