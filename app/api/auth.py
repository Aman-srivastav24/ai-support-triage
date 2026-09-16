"""Authentication endpoints: register and login."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token
from app.schemas.user import Token, UserRead, UserRegister
from app.services.auth import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    authenticate_user,
    create_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: UserRegister, db: DbSession) -> UserRead:
    """Create an agent account."""
    try:
        user = create_user(
            db, email=payload.email, password=payload.password
        )
    except EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """Exchange email and password for a JWT."""
    try:
        user = authenticate_user(
            db, email=form_data.username, password=form_data.password
        )
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    return Token(access_token=create_access_token(user.id, user.role))


@router.get("/me", response_model=UserRead)
def read_current_user(user: CurrentUser) -> UserRead:
    """Return the authenticated user. Proves the token works."""
    return user