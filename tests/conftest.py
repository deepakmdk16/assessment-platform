"""Test fixtures: a temp in-memory SQLite DB and TestClients wired to it.

Tests never touch the real `platform.db` and never hit the network.

- `anon_client`: no auth header (auth endpoints, ownership tests managing their
  own tokens, public candidate endpoints).
- `client`: `anon_client` plus a registered default interviewer whose bearer
  token is set as the default Authorization header, so the interviewer-owned
  routes (questions, etc.) work without each test re-doing the auth dance.
"""

from __future__ import annotations

import os

# Mark the process as test mode BEFORE importing anything that reads config, so a
# developer's real .env (which config loads) can't make the suite send live email.
os.environ.setdefault("PLATFORM_TESTING", "1")

from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.api import app
from assessment_platform.db import get_session
from assessment_platform.ratelimit import limiter


def async_return(value: Any) -> Callable[..., Awaitable[Any]]:
    """An async stand-in for a mocked agent call that resolves to `value`.

    The agent_client functions are now coroutines the routes `await`, so a plain
    `lambda` returning a value is not awaitable — use this to patch them."""

    async def _stub(*_a: Any, **_k: Any) -> Any:
        return value

    return _stub


def async_raise(exc: BaseException) -> Callable[..., Awaitable[Any]]:
    """Like `async_return`, but the awaited call raises `exc`."""

    async def _stub(*_a: Any, **_k: Any) -> Any:
        raise exc

    return _stub


def patch_async_post(
    monkeypatch: pytest.MonkeyPatch,
    on_post: Callable[..., httpx.Response],
) -> None:
    """Patch `httpx.AsyncClient` so the agent's outbound POST is intercepted.

    `on_post(url, timeout, **post_kwargs)` returns the Response; `timeout` is the
    value passed to the client constructor (where httpx.AsyncClient takes it),
    the rest are the `.post()` kwargs (content, headers)."""

    class _FakeAsyncClient:
        def __init__(self, *_a: Any, **kw: Any) -> None:
            self._timeout = kw.get("timeout")

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

        async def post(self, url: str, **kw: Any) -> httpx.Response:
            return on_post(url, self._timeout, **kw)

    monkeypatch.setattr(agent_client.httpx, "AsyncClient", _FakeAsyncClient)


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    # The limiter is process-global; clear it between tests so counts from one
    # test don't bleed into the next (they share the fast monotonic window).
    limiter.reset()
    yield


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
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


def register_interviewer(
    client: TestClient, email: str, password: str = "pw", name: str = "Tester"
) -> str:
    """Register + log in an interviewer; return a bearer token."""
    client.post("/auth/register", json={"email": email, "password": password, "name": name})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return resp.json()["access_token"]


@pytest.fixture
def client(anon_client: TestClient) -> Iterator[TestClient]:
    token = register_interviewer(anon_client, "owner@test.io", name="Owner")
    anon_client.headers["Authorization"] = f"Bearer {token}"
    yield anon_client
