import enum
import secrets
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.user import User


def new_display_token() -> str:
    """Opaque, guessable-proof, and short enough to type on a TV remote if it
    ever comes to that."""
    return secrets.token_urlsafe(18)


class CampaignRole(enum.StrEnum):
    """Scoped to one table. Separate from `users.role`, which governs the
    installation — you can be a global admin and still just a player here."""

    PLAYER = "player"
    DM = "dm"


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Lets a TV or second browser window open the cast display without a login.
    # Rotatable, so a leaked URL is a nuisance rather than a problem.
    display_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=new_display_token, nullable=False
    )

    owner: Mapped["User"] = relationship()
    members: Mapped[list["CampaignMember"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )
    entities: Mapped[list["Entity"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Campaign {self.name}>"


class CampaignMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_member_per_campaign"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[CampaignRole] = mapped_column(
        Enum(CampaignRole, name="campaign_role", values_callable=lambda e: [m.value for m in e]),
        default=CampaignRole.PLAYER,
        nullable=False,
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(lazy="selectin")

    @property
    def is_dm(self) -> bool:
        return self.role is CampaignRole.DM
