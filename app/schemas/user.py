"""Pydantic schemas for the auth endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegister(BaseModel):
    """Body of POST /auth/register."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserRead(BaseModel):
    """A user as returned by the API. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """Body of the POST /auth/login response."""

    access_token: str
    token_type: str = "bearer"