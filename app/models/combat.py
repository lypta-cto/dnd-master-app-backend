import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CombatState(UUIDMixin, TimestampMixin, Base):
    """
    The running fight — one per campaign, like the cast state.

    Combatants live in JSONB rather than rows: a fight is a short-lived working
    set the DM rewrites constantly (initiative, HP, conditions), not archival
    data anyone queries later. Whole-state PUTs keep the API one call per
    change, which is what a table's pace demands.
    """

    __tablename__ = "combat_states"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # [{id, name, kind: character|monster|custom, entity_id?, initiative,
    #   max_hp?, current_hp?, conditions: []}]
    combatants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
