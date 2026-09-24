"""Shared FastAPI dependencies for the API layer.

This is where our own exceptions become HTTP status codes.
"""

from __future__ import annotations
from app.services.providers import Embedder, LLMClient, get_embedder, get_llm
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

DbSession = Annotated[Session, Depends(get_db)]
LLMProvider = Annotated[LLMClient, Depends(get_llm)]
EmbeddingProvider = Annotated[Embedder, Depends(get_embedder)]

def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Turn a bearer token into the User it identifies."""
    try:
        claims = decode_access_token(token)
    except TokenError:
        raise _CREDENTIALS_ERROR from None

    subject = claims.get("sub")
    if subject is None:
        raise _CREDENTIALS_ERROR

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise _CREDENTIALS_ERROR from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """Allow only admins through."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]