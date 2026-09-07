"""Interviewer authentication: password policy + hashing, JWT sessions, and the
single-purpose tokens behind email verification and password reset.

Passwords are hashed with bcrypt. A session is two stateless JWTs: a short-lived
*access* token the SPA holds in memory and sends as a bearer, and a long-lived
*refresh* token that only ever travels in an httpOnly cookie scoped to `/auth`,
so script on the page (XSS) can neither read it nor send it anywhere but the
auth routes. Every token carries the interviewer's `token_version`; bumping
that column (password change or reset) voids every token minted before it —
the revocation switch a stateless JWT otherwise lacks.

`get_current_interviewer` is the FastAPI dependency that guards the
interviewer-only routes — a missing/invalid token is a 401.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from . import config
from .db import get_session
from .models import Interviewer

logger = logging.getLogger(__name__)

# auto_error=False so a missing token yields our own 401 (not HTTPBearer's 403).
_bearer = HTTPBearer(auto_error=False)

# Password policy. Length is the one property that reliably resists offline
# cracking; composition rules mostly produce Password1!. bcrypt reads at most 72
# bytes (bcrypt>=5 raises beyond that), so the ceiling is a byte count.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_BYTES = 72

REFRESH_COOKIE = "refresh_token"
# The browser only ever sends the cookie to the auth routes, so it can't ride
# along on a cross-site request to anything that changes state.
REFRESH_COOKIE_PATH = "/auth"

VERIFY_TOKEN_TTL = timedelta(days=3)
RESET_TOKEN_TTL = timedelta(hours=1)


# --------------------------------------------------------------------------- #
# Passwords                                                                     #
# --------------------------------------------------------------------------- #


def check_password_policy(password: str) -> str:
    """Pydantic AfterValidator for every field that sets a password."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"password must be at most {PASSWORD_MAX_BYTES} bytes.")
    return password


def is_breached_password(password: str) -> bool:
    """True if the password is in Have I Been Pwned's corpus of leaked passwords.

    k-anonymity: only the first 5 hex chars of the SHA-1 leave the machine; the
    suffix is matched locally. Fails OPEN — creating an account must not depend
    on a third party being up — and is off under test / by config.
    """
    if not config.PASSWORD_BREACH_CHECK:
        return False
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        resp = httpx.get(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            # Padded responses hide the real match count from a network observer.
            headers={"Add-Padding": "true"},
            timeout=5.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("password breach check unavailable (%s); allowing the password.", exc)
        return False
    for line in resp.text.splitlines():
        hash_suffix, _, count = line.partition(":")
        if hash_suffix.strip() == suffix and count.strip() != "0":
            return True
    return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Tokens                                                                        #
# --------------------------------------------------------------------------- #


def _encode(claims: dict[str, Any], ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**claims, "iat": now, "exp": now + ttl}, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM
    )


def _decode(token: str, use: str) -> dict[str, Any] | None:
    """The claims of a valid, unexpired token minted for `use`, else None. The
    `use` claim keeps the token kinds apart: a reset link can't be replayed as a
    bearer, a refresh cookie can't be pasted in as an access token."""
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("use") == use else None


def _subject(payload: dict[str, Any], session: Session) -> Interviewer | None:
    try:
        return session.get(Interviewer, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        return None


def _session_claims(interviewer: Interviewer) -> dict[str, Any]:
    return {"sub": str(interviewer.id), "ver": interviewer.token_version}


def create_access_token(interviewer: Interviewer) -> str:
    return _encode(
        {"use": "access", **_session_claims(interviewer)},
        timedelta(minutes=config.JWT_EXPIRE_MIN),
    )


def create_refresh_token(interviewer: Interviewer) -> str:
    return _encode(
        {"use": "refresh", **_session_claims(interviewer)},
        timedelta(days=config.REFRESH_EXPIRE_DAYS),
    )


def _session_interviewer(token: str, use: str, session: Session) -> Interviewer | None:
    payload = _decode(token, use)
    if payload is None:
        return None
    interviewer = _subject(payload, session)
    if interviewer is None or payload.get("ver") != interviewer.token_version:
        return None
    return interviewer


def get_current_interviewer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Interviewer:
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token.")
    interviewer = _session_interviewer(creds.credentials, "access", session)
    if interviewer is None:
        raise HTTPException(status_code=401, detail="invalid or expired token.")
    return interviewer


def interviewer_from_refresh(token: str | None, session: Session) -> Interviewer | None:
    return None if token is None else _session_interviewer(token, "refresh", session)


def _hash_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_verify_token(interviewer: Interviewer) -> str:
    return _encode(
        {"use": "verify", "sub": str(interviewer.id), "email": interviewer.email},
        VERIFY_TOKEN_TTL,
    )


def create_reset_token(interviewer: Interviewer) -> str:
    # Bound to the current hash, which makes a reset link single-use: once the
    # password changes — through this link or any other route — the binding no
    # longer matches and the link is dead.
    return _encode(
        {
            "use": "reset",
            "sub": str(interviewer.id),
            "pwd": _hash_fingerprint(interviewer.password_hash),
        },
        RESET_TOKEN_TTL,
    )


def interviewer_from_action_token(token: str, use: str, session: Session) -> Interviewer | None:
    """The account a `verify` / `reset` link belongs to, or None if the link is
    invalid, expired, or no longer applies (address changed, password already
    changed)."""
    payload = _decode(token, use)
    if payload is None:
        return None
    interviewer = _subject(payload, session)
    if interviewer is None:
        return None
    if use == "verify" and payload.get("email") != interviewer.email:
        return None
    if use == "reset" and payload.get("pwd") != _hash_fingerprint(interviewer.password_hash):
        return None
    return interviewer


# --------------------------------------------------------------------------- #
# Refresh cookie                                                                #
# --------------------------------------------------------------------------- #


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=config.REFRESH_EXPIRE_DAYS * 86400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
    )
