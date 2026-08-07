import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class RunState(UUIDMixin, TimestampMixin, Base):
    """
    The evening in progress — one per campaign, like the fight and the cast.

    Prep lives in entities; this is the small amount of state that only means
    anything while people are at the table: which scene you're in, which clues
    you've actually handed over, who has had a moment, and what the clock is
    doing regardless of where the party wandered.

    JSONB and whole-state PUTs for the same reason as combat: it's a working
    set the DM rewrites constantly, not archival data anyone queries later.
    """

    __tablename__ = "run_states"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The session entity being played, and the scene currently on the table.
    # Plain columns rather than FKs: a deleted scene should leave the run
    # standing, not cascade into it mid-evening.
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    scene_id: Mapped[uuid.UUID | None] = mapped_column()

    # Clue entity ids the party actually has now
    revealed: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # {player_id: times they've had the spotlight} — the count that stops two
    # people from playing the whole evening for eight
    spotlight: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # [{label, text, done}] — the world's clock: things that happen whether or
    # not the party is there to see them
    clock: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # Scratch notes for the evening, emptied when it ends
    notes: Mapped[str | None] = mapped_column(Text)
