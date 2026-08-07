import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.entity import Entity
    from app.models.user import User


class Player(UUIDMixin, TimestampMixin, Base):
    """A seat at the table — a person, not an account.

    Most players never log in: the DM writes them down once and that's the end
    of it. An account is optional and arrives later, if ever, through `user_id`.
    Keeping the two apart is what lets a one-shot for eight people be set up in
    a couple of minutes.

    Permissions still hang off `user_id` (via the character's `owner_id`), so a
    player without an account simply has nothing to permit.
    """

    __tablename__ = "players"
    __table_args__ = (
        # One seat per account per campaign. Several NULLs are fine — that's the
        # normal case, people who never registered.
        UniqueConstraint("campaign_id", "user_id", name="uq_player_account_per_campaign"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Free text on purpose: Discord handle, phone, "brother's friend"
    contact: Mapped[str | None] = mapped_column(String(160))
    # new | some | veteran — how much hand-holding the table needs
    experience: Mapped[str | None] = mapped_column(String(20))
    # combat / roleplay / puzzles / exploration — what to aim their scenes at
    preferences: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default="{}", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(1000))

    # Set once they accept an invitation; until then this seat is DM-managed
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Where the invitation went, so a later registration can find its seat
    invited_email: Mapped[str | None] = mapped_column(String(255), index=True)

    campaign: Mapped["Campaign"] = relationship()
    user: Mapped["User | None"] = relationship(lazy="selectin")
    characters: Mapped[list["Entity"]] = relationship(back_populates="player", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Player {self.name}>"
