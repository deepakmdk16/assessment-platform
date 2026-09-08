"""P13 — account lifecycle: password policy + breach check, lower-cased emails,
access/refresh sessions with token_version revocation, email verification,
password reset / change, and account deletion."""

from __future__ import annotations

import hashlib
from typing import Any

import httpx
import jwt
import pytest
from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_slice1 import _auth, _make_invite, _sample_question

from assessment_platform import api, auth, config, db, email_client
from assessment_platform.models import Interviewer, Invite, Question, QuestionTestCase

PW = "correct-horse-battery-staple"
NEW_PW = "another-long-password-42"


@pytest.fixture
def outbox(monkeypatch) -> list[dict[str, str]]:
    """Capture account emails (verification / reset links) instead of logging them."""
    box: list[dict[str, str]] = []

    def fake(to: str, subject: str, body: str, url: str) -> email_client.Delivery:
        box.append({"to": to, "subject": subject, "url": url})
        return email_client.Delivery(to, sent=True)

    monkeypatch.setattr(email_client, "send_account_email", fake)
    return box


def _register(client: TestClient, email: str, password: str = PW) -> Any:
    return client.post("/auth/register", json={"email": email, "password": password, "name": "A"})


def _login(client: TestClient, email: str, password: str = PW) -> Any:
    return client.post("/auth/login", json={"email": email, "password": password})


def _link_token(url: str) -> str:
    return url.rsplit("token=", 1)[1]


# --------------------------------------------------------------------------- #
# Password policy                                                               #
# --------------------------------------------------------------------------- #


def test_register_enforces_password_length(anon_client: TestClient) -> None:
    assert _register(anon_client, "a@x.io", "elevenchars").status_code == 422
    assert _register(anon_client, "a@x.io", "x" * 73).status_code == 422
    # 12 chars is the floor; 72 bytes the bcrypt ceiling.
    assert _register(anon_client, "a@x.io", "twelve-chars").status_code == 201
    assert _register(anon_client, "b@x.io", "y" * 72).status_code == 201


def test_register_rejects_breached_password(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(api, "is_breached_password", lambda _pw: True)
    resp = _register(anon_client, "a@x.io")
    assert resp.status_code == 422
    assert "breach" in resp.json()["detail"]


def test_breach_check_sends_only_a_prefix_and_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(config, "PASSWORD_BREACH_CHECK", True)
    digest = hashlib.sha1(PW.encode()).hexdigest().upper()
    seen: list[str] = []

    class _Resp:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, **_kw: Any) -> _Resp:
        seen.append(url)
        # The real API answers with suffixes; a padded (count 0) line must not match.
        return _Resp(f"AAAAAAAA:0\r\n{digest[5:]}:42\r\n")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert auth.is_breached_password(PW) is True
    assert seen[0].endswith(f"/range/{digest[:5]}")
    assert digest[5:] not in seen[0]

    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: _Resp(f"{digest[5:]}:0\r\n"))
    assert auth.is_breached_password(PW) is False  # padding only

    def down(*_a: Any, **_k: Any) -> _Resp:
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "get", down)
    assert auth.is_breached_password(PW) is False  # fail open

    monkeypatch.setattr(config, "PASSWORD_BREACH_CHECK", False)
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: pytest.fail("must not call out"))
    assert auth.is_breached_password(PW) is False


# --------------------------------------------------------------------------- #
# Email normalisation                                                           #
# --------------------------------------------------------------------------- #


def test_emails_are_case_insensitive(anon_client: TestClient) -> None:
    resp = _register(anon_client, "Jane@X.io")
    assert resp.status_code == 201
    assert resp.json()["email"] == "jane@x.io"
    assert _login(anon_client, "JANE@x.io").status_code == 200
    assert _register(anon_client, "jane@x.io").status_code == 409
    assert _register(anon_client, "JANE@X.IO").status_code == 409


# --------------------------------------------------------------------------- #
# Sessions: access + refresh cookie, revocation                                 #
# --------------------------------------------------------------------------- #


def test_login_sets_httponly_refresh_cookie_scoped_to_auth(anon_client: TestClient) -> None:
    _register(anon_client, "a@x.io")
    resp = _login(anon_client, "a@x.io")
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith("refresh_token=")
    assert "HttpOnly" in set_cookie and "Path=/auth" in set_cookie and "SameSite=lax" in set_cookie
    # The refresh token is not a bearer: it must be useless as an access token.
    refresh = resp.cookies["refresh_token"]
    assert anon_client.get("/auth/me", headers=_auth(refresh)).status_code == 401


def test_refresh_issues_a_working_access_token_and_rotates(anon_client: TestClient) -> None:
    _register(anon_client, "a@x.io")
    assert _login(anon_client, "a@x.io").status_code == 200
    resp = anon_client.post("/auth/refresh")  # cookie jar sends refresh_token to /auth/*
    assert resp.status_code == 200
    assert anon_client.get("/auth/me", headers=_auth(resp.json()["access_token"])).status_code == 200
    # Sliding session: every refresh re-issues the cookie (same second → same
    # bytes, so check the Set-Cookie, not the value).
    assert resp.headers["set-cookie"].startswith("refresh_token=")

    anon_client.cookies.clear()
    assert anon_client.post("/auth/refresh").status_code == 401
    assert anon_client.post("/auth/refresh", headers={"Cookie": "refresh_token=junk"}).status_code == 401


def test_logout_clears_the_refresh_cookie(anon_client: TestClient) -> None:
    _register(anon_client, "a@x.io")
    _login(anon_client, "a@x.io")
    assert anon_client.post("/auth/refresh").status_code == 200
    resp = anon_client.post("/auth/logout")
    assert resp.status_code == 204
    assert 'refresh_token=""' in resp.headers["set-cookie"]
    assert anon_client.post("/auth/refresh").status_code == 401


def test_change_password_revokes_every_other_session(anon_client: TestClient) -> None:
    _register(anon_client, "a@x.io")
    login = _login(anon_client, "a@x.io")
    old_access, old_refresh = login.json()["access_token"], login.cookies["refresh_token"]

    resp = anon_client.post(
        "/auth/change-password",
        json={"current_password": "wrong-password-x", "new_password": NEW_PW},
        headers=_auth(old_access),
    )
    assert resp.status_code == 403
    resp = anon_client.post(
        "/auth/change-password",
        json={"current_password": PW, "new_password": "short"},
        headers=_auth(old_access),
    )
    assert resp.status_code == 422

    resp = anon_client.post(
        "/auth/change-password",
        json={"current_password": PW, "new_password": NEW_PW},
        headers=_auth(old_access),
    )
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    # This device carries on with its fresh session; everything older is dead.
    assert anon_client.get("/auth/me", headers=_auth(new_access)).status_code == 200
    assert anon_client.get("/auth/me", headers=_auth(old_access)).status_code == 401
    anon_client.cookies.clear()
    assert (
        anon_client.post("/auth/refresh", headers={"Cookie": f"refresh_token={old_refresh}"})
        .status_code
        == 401
    )
    assert _login(anon_client, "a@x.io", PW).status_code == 401
    assert _login(anon_client, "a@x.io", NEW_PW).status_code == 200


# --------------------------------------------------------------------------- #
# Forgot / reset                                                                #
# --------------------------------------------------------------------------- #


def test_forgot_password_never_reveals_whether_an_account_exists(
    anon_client: TestClient, outbox: list[dict[str, str]]
) -> None:
    _register(anon_client, "a@x.io")
    outbox.clear()  # the verification mail
    unknown = anon_client.post("/auth/forgot-password", json={"email": "ghost@x.io"})
    known = anon_client.post("/auth/forgot-password", json={"email": "A@x.io"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert [m["to"] for m in outbox] == ["a@x.io"]
    assert outbox[0]["url"].startswith(f"{config.FRONTEND_BASE_URL}/reset-password?token=")


def test_reset_link_is_single_use_and_signs_out_old_sessions(
    anon_client: TestClient, outbox: list[dict[str, str]]
) -> None:
    _register(anon_client, "a@x.io")
    old_access = _login(anon_client, "a@x.io").json()["access_token"]
    anon_client.post("/auth/forgot-password", json={"email": "a@x.io"})
    token = _link_token(outbox[-1]["url"])
    # The page greets the address from the token's payload (informational only).
    assert jwt.decode(token, options={"verify_signature": False})["email"] == "a@x.io"

    assert anon_client.get("/auth/me", headers=_auth(token)).status_code == 401  # not a bearer
    assert anon_client.post("/auth/verify-email", json={"token": token}).status_code == 400
    resp = anon_client.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert resp.status_code == 422
    resp = anon_client.post("/auth/reset-password", json={"token": "junk", "new_password": NEW_PW})
    assert resp.status_code == 400

    resp = anon_client.post("/auth/reset-password", json={"token": token, "new_password": NEW_PW})
    assert resp.status_code == 204
    assert _login(anon_client, "a@x.io", PW).status_code == 401
    login = _login(anon_client, "a@x.io", NEW_PW)
    assert login.status_code == 200
    assert anon_client.get("/auth/me", headers=_auth(old_access)).status_code == 401
    # Following the mailed link proved control of the address.
    me = anon_client.get("/auth/me", headers=_auth(login.json()["access_token"])).json()
    assert me["email_verified"] is True
    # Bound to the hash it was issued against: a second use is refused.
    resp = anon_client.post("/auth/reset-password", json={"token": token, "new_password": PW})
    assert resp.status_code == 400
    assert _login(anon_client, "a@x.io", NEW_PW).status_code == 200


def test_forgot_password_is_rate_limited(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT_MAX", 3)
    codes = [
        anon_client.post("/auth/forgot-password", json={"email": "x@x.io"}).status_code
        for _ in range(4)
    ]
    assert codes == [202, 202, 202, 429]


# --------------------------------------------------------------------------- #
# Email verification                                                            #
# --------------------------------------------------------------------------- #


def test_email_verification_flow(anon_client: TestClient, outbox: list[dict[str, str]]) -> None:
    _register(anon_client, "a@x.io")
    assert [m["to"] for m in outbox] == ["a@x.io"]
    assert outbox[0]["url"].startswith(f"{config.FRONTEND_BASE_URL}/verify-email?token=")
    token = _link_token(outbox[0]["url"])
    access = _login(anon_client, "a@x.io").json()["access_token"]
    assert anon_client.get("/auth/me", headers=_auth(access)).json()["email_verified"] is False

    assert anon_client.post("/auth/verify-email", json={"token": "junk"}).status_code == 400
    assert anon_client.post("/auth/verify-email", json={"token": token}).status_code == 204
    assert anon_client.get("/auth/me", headers=_auth(access)).json()["email_verified"] is True
    assert anon_client.post("/auth/verify-email", json={"token": token}).status_code == 204

    resp = anon_client.post("/auth/resend-verification", headers=_auth(access))
    assert resp.status_code == 202 and "already" in resp.json()["detail"]
    assert len(outbox) == 1

    _register(anon_client, "b@x.io")
    access_b = _login(anon_client, "b@x.io").json()["access_token"]
    resp = anon_client.post("/auth/resend-verification", headers=_auth(access_b))
    assert resp.status_code == 202
    assert [m["to"] for m in outbox] == ["a@x.io", "b@x.io", "b@x.io"]
    assert anon_client.post("/auth/resend-verification").status_code == 401


# --------------------------------------------------------------------------- #
# Account deletion                                                              #
# --------------------------------------------------------------------------- #


def test_delete_account_purges_owned_data_only(anon_client: TestClient) -> None:
    doomed = register_interviewer(anon_client, "doomed@x.io", password=PW)
    _make_invite(anon_client, doomed)
    keeper = register_interviewer(anon_client, "keeper@x.io", password=PW)
    anon_client.post("/questions", json=_sample_question("keep_me"), headers=_auth(keeper))

    resp = anon_client.request(
        "DELETE", "/auth/me", json={"password": "wrong-password-x"}, headers=_auth(doomed)
    )
    assert resp.status_code == 403
    assert anon_client.request("DELETE", "/auth/me", json={"password": PW}).status_code == 401

    resp = anon_client.request("DELETE", "/auth/me", json={"password": PW}, headers=_auth(doomed))
    assert resp.status_code == 204
    assert 'refresh_token=""' in resp.headers["set-cookie"]
    assert anon_client.get("/auth/me", headers=_auth(doomed)).status_code == 401
    assert _login(anon_client, "doomed@x.io").status_code == 401

    with Session(db.engine) as s:
        assert [i.email for i in s.exec(select(Interviewer)).all()] == ["keeper@x.io"]
        assert [q.id for q in s.exec(select(Question)).all()] == ["keep_me"]
        assert s.exec(select(Invite)).all() == []
        assert {tc.question_id for tc in s.exec(select(QuestionTestCase)).all()} == {"keep_me"}
    assert anon_client.get("/questions", headers=_auth(keeper)).status_code == 200
