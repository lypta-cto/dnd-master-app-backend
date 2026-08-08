import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ARRAY,
    Computed,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.player import Player


class EntityType(enum.StrEnum):
    """Adding a type here costs nothing — no table, no CRUD, no search branch.
    Type-specific fields live in `Entity.data` and are validated per type by the
    schemas in app/schemas/entity.py."""

    NPC = "npc"
    CHARACTER = "character"  # player character — the one type a player may edit
    LOCATION = "location"
    ITEM = "item"
    FACTION = "faction"
    NOTE = "note"
    SESSION = "session"  # one evening at the table: prep before, recap after
    QUEST = "quest"  # a story thread with a status — the campaign's spine
    MONSTER = "monster"  # statblock in `data`, always DM-only by default
    MAP = "map"  # an image with pins; each pin points at an entity
    SCENE = "scene"  # a beat you run: purpose, what they learn, where it can go
    ENCOUNTER = "encounter"  # combat, social, puzzle, chase — with an objective
    CLUE = "clue"  # a fact the party can find, and what it points toward


class Visibility(enum.StrEnum):
    DM_ONLY = "dm_only"
    SHARED = "shared"
    PUBLIC = "public"


class LinkRelation(enum.StrEnum):
    MENTIONS = "mentions"  # written by the [[wiki link]] parser
    MEMBER_OF = "member_of"
    LOCATED_IN = "located_in"
    OWNS = "owns"
    RELATED_TO = "related_to"
    LEADS_TO = "leads_to"  # scene → scene: the campaign's flowchart


class Entity(UUIDMixin, TimestampMixin, Base):
    """The spine. Every noun in a campaign is one of these."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("campaign_id", "slug", name="uq_entity_slug_per_campaign"),
        Index("ix_entities_search", "search_vector", postgresql_using="gin"),
        Index("ix_entities_campaign_type", "campaign_id", "type"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Set only on characters: the account that may edit this sheet. Ownership is
    # what grants a non-DM write access, and it always beats visibility for
    # reading. Empty for the common case — a player who never registered.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Set only on characters: whose sheet this is at the table. Independent of
    # `owner_id` on purpose — a seat exists whether or not anyone logs in, and
    # deleting a player leaves their character behind rather than the story.
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True
    )

    type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)  # markdown, with [[wiki links]]

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list, nullable=False)

    image_url: Mapped[str | None] = mapped_column(String(1024))

    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="entity_visibility", values_callable=lambda e: [m.value for m in e]),
        default=Visibility.DM_ONLY,
        nullable=False,
    )

    # Maintained by Postgres, so it can never drift from the text it indexes.
    # Name is weighted above summary above body, so a search for "Blackmoor"
    # ranks the keep itself over every note that mentions it.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        # `immutable_unaccent` is ours — a generated column demands IMMUTABLE
        # and unaccent is only STABLE. See the migration for why pinning the
        # dictionary makes it honest rather than a lie about determinism.
        Computed(
            "setweight(to_tsvector('simple', immutable_unaccent(coalesce(name, ''))), 'A') || "
            "setweight(to_tsvector('simple', immutable_unaccent(coalesce(summary, ''))), 'B') || "
            "setweight(to_tsvector('simple', immutable_unaccent(coalesce(body, ''))), 'C')",
            persisted=True,
        ),
        nullable=False,
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="entities")
    player: Mapped["Player | None"] = relationship(back_populates="characters")

    def __repr__(self) -> str:
        return f"<Entity {self.type.value}:{self.name}>"


class EntityLink(Base, UUIDMixin, TimestampMixin):
    """One table for every kind of connection, which is what keeps 'link
    anything to anything' from turning into a pile of join tables."""

    __tablename__ = "entity_links"
    __table_args__ = (
        UniqueConstraint("from_id", "to_id", "relation", name="uq_entity_link"),
        Index("ix_entity_links_to", "to_id"),  # backlinks read this
    )

    from_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[LinkRelation] = mapped_column(
        Enum(LinkRelation, name="link_relation", values_callable=lambda e: [m.value for m in e]),
        default=LinkRelation.MENTIONS,
        nullable=False,
    )
