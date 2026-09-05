from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import Settings


class Base(DeclarativeBase):
    pass


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    return sessionmaker(bind=engine, expire_on_commit=False)


def ensure_schema(session_factory: sessionmaker[Session]) -> None:
    """Create new tables and apply the additive Stage 1.1 RawEvent migration.

    This project intentionally has no migration framework yet.  The migration is
    additive and portable across the supported SQLite and PostgreSQL deployments,
    so existing Stage 1 installations can safely gain the indexed correlation
    columns while a later release adopts Alembic.
    """

    # Register all mapped tables when this function is called by maintenance code
    # that imported database.py directly rather than the application entry point.
    from . import models as _models  # noqa: F401
    from .stage2 import models as _stage2_models  # noqa: F401
    from .stage3 import models as _stage3_models  # noqa: F401

    engine = session_factory.kw["bind"]
    inspector = inspect(engine)
    additive_columns = {
        "raw_events": {
            "merchant_id": "VARCHAR(255)",
            "order_id": "VARCHAR(255)",
            "payment_id": "VARCHAR(255)",
            "occurred_at": "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME",
        },
        "dead_letter_events": {"first_error": "TEXT"},
        "recovery_cases": {
            "source_event_ids": "JSON" if engine.dialect.name == "postgresql" else "TEXT",
            "stage1_state_version": "INTEGER",
        },
    }
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, required in additive_columns.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, column_type in required.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"))
        if "dead_letter_events" in tables:
            connection.execute(text("UPDATE dead_letter_events SET first_error = last_error WHERE first_error IS NULL"))
    Base.metadata.create_all(engine)
    # create_all skips existing tables, so make new indexes explicit for upgraded
    # Stage 1 databases as well as clean installations.
    for index in Base.metadata.tables["raw_events"].indexes:
        index.create(engine, checkfirst=True)
