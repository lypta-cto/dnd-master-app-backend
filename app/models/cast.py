import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CastMode(enum.StrEnum):
    IDLE = "idle"
    IMAGE = "image"
    SLIDESHOW = "slideshow"
    TEXT = "text"
    INITIATIVE = "initiative"  # MVP-3
    DICE = "dice"  # a roll result, for drama
    MAP = "map"  # MVP-4


class CastState(UUIDMixin, TimestampMixin, Base):
    """
    What the table is looking at right now — one row per campaign.

    The whole cast feature is this row plus a stream. It is deliberately *not*
    collaborative: the DM writes, the display reads, nobody types into it. That
    is why there is no locking, no presence and no conflict resolution here.
    """

    __tablename__ = "cast_states"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    mode: Mapped[CastMode] = mapped_column(
        Enum(CastMode, name="cast_mode", values_callable=lambda e: [m.value for m in e]),
        default=CastMode.IDLE,
        nullable=False,
    )

    # Shape depends on `mode` — see app/schemas/cast.py
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
