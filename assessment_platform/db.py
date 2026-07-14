"""Database engine and session wiring.

v1 uses `SQLModel.metadata.create_all` on startup (no Alembic yet). SQLite needs
`check_same_thread=False` because FastAPI serves requests across threads; that
arg is silently dropped for non-SQLite URLs, so the Postgres swap stays URL-only.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_URL


def make_engine(url: str = DATABASE_URL) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine: Engine = make_engine()


def init_db(bind: Engine | None = None) -> None:
    """Create all tables. Import models first so they register on the metadata."""
    from . import models  # noqa: F401  (registers tables on SQLModel.metadata)

    SQLModel.metadata.create_all(bind or engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    with Session(engine) as session:
        yield session
