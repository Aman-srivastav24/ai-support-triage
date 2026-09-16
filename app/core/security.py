"""Password hashing and JWT creation/verification.

The only module in the app that imports bcrypt or jwt.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

_BCRYPT_ROUNDS = 12
_MAX_PASSWORD_BYTES = 72


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or tampered with."""


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt. Returns salt + hash as one string."""
    password_bytes = plain_password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Check a password against a stored hash. Never raises on bad input."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:_MAX_PASSWORD_BYTES],
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    """Mint a signed JWT carrying the user's id and role."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature and expiry, and return the claims.

    Raises TokenError for any invalid token.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid") from exc