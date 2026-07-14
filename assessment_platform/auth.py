"""Interviewer authentication: password hashing + JWT bearer tokens.

Passwords are hashed with bcrypt; sessions are stateless JWTs (subject = the
interviewer's id). `get_current_interviewer` is the FastAPI dependency that
guards the interviewer-only routes — a missing/invalid token is a 401.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from . import config
from .db import get_session
from .models import Interviewer

# auto_error=False so a missing token yields our own 401 (not HTTPBearer's 403).
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(interviewer_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(interviewer_id),
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def get_current_interviewer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> Interviewer:
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token.")
    try:
        payload = jwt.decode(
            creds.credentials, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM]
        )
        interviewer_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token.") from exc

    interviewer = session.get(Interviewer, interviewer_id)
    if interviewer is None:
        raise HTTPException(status_code=401, detail="unknown interviewer.")
    return interviewer
