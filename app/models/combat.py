import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Uuid
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

    # Which map the fight is happening on, when it's happening on one. Not a
    # foreign key: deleting a map mid-session should lose the battle map, not
    # cascade into the fight the table is in the middle of.
    map_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # [{id, name, kind: character|monster|custom, entity_id?, initiative,
    #   max_hp?, current_hp?, conditions: [], x?, y?}]
    # x and y are percentages of the map, so a token lands in the same place on
    # the DM's laptop and the table's TV.
    combatants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
