"""Authentication business logic. Knows nothing about HTTP."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole

# Used to equalise timing when an email doesn't exist. Never matches anything.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.2qBqT1n5a5Y1z5X5Q5W5E5R5T5Y5U5i"


class EmailAlreadyRegistered(Exception):
    """Raised when the email is already in the users table."""


class InvalidCredentials(Exception):
    """Raised when login fails, for any reason."""


def get_user_by_email(db: Session, email: str) -> User | None:
    """Look a user up by email. Returns None if not found."""
    return db.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    role: UserRole = UserRole.AGENT,
) -> User:
    """Create a user. Raises EmailAlreadyRegistered on a duplicate email."""
    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegistered(email)

    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EmailAlreadyRegistered(email) from exc

    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    """Return the user if the credentials are valid, else raise InvalidCredentials."""
    user = get_user_by_email(db, email)

    if user is None:
        # Hash anyway so a missing email costs the same time as a wrong password.
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentials

    if not verify_password(password, user.hashed_password):
        raise InvalidCredentials

    if not user.is_active:
        raise InvalidCredentials

    return user