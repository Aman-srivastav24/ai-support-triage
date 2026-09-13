from typing import TYPE_CHECKING
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.ticket import Ticket


class UserRole(StrEnum):
    AGENT = "agent"
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('agent', 'admin')", name="ck_users_role"),
    )

    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.AGENT,
        server_default=UserRole.AGENT.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    documents: Mapped[list["Document"]] = relationship(back_populates="uploaded_by")
    assigned_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="assigned_agent"
    )