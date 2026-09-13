import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.ticket_citation import TicketCitation
    from app.models.user import User


class TicketStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    DRAFTED = "drafted"
    ESCALATED = "escalated"
    FAILED = "failed"
    RESOLVED = "resolved"


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'processing', 'drafted', 'escalated', 'failed', 'resolved')",
            name="ck_tickets_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_tickets_confidence_range",
        ),
    )

    customer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TicketStatus.RECEIVED,
        server_default=TicketStatus.RECEIVED.value,
        index=True,
    )
    category: Mapped[str | None] = mapped_column(String(50))
    draft_reply: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assigned_agent: Mapped["User | None"] = relationship(
        back_populates="assigned_tickets"
    )
    citations: Mapped[list["TicketCitation"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketCitation.rank",
    )