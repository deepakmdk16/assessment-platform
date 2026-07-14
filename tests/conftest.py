"""Test fixtures: a temp-file SQLite DB and a TestClient wired to it.

We build a throwaway engine per test and override the app's `get_session`
dependency so tests never touch the real `platform.db` and never hit the network.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from assessment_platform import db as db_module
from assessment_platform.api import app
from assessment_platform.db import get_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    # In-memory SQLite shared across connections via StaticPool.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    # Point the module engine at the test engine too, so the startup init_db and
    # any direct `engine` use land on the same in-memory DB.
    db_module.engine = engine

    def _get_session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _get_session_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
