from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import Settings


class Base(DeclarativeBase):
    pass


def build_session_factory(settings: Settings) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    return sessionmaker(bind=engine, expire_on_commit=False)

