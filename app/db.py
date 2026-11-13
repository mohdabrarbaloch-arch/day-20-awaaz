"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine(url: str):
    """Build an engine with the right options for the backend in use."""
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        # SQLite ignores foreign keys unless explicitly switched on, which
        # would let orphaned segments survive a deleted transcription.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Real deployments should use Alembic migrations."""
    from app import models  # noqa: F401  (import registers the models)

    Base.metadata.create_all(bind=engine)
