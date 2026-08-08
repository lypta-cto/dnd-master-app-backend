import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.entity import EntityType, LinkRelation, Visibility


class EntityBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    visibility: Visibility = Visibility.DM_ONLY
    # Type-specific fields. Free-form for now, on purpose — the shapes are still
    # moving. Tighten with a per-type model once they settle.
    data: dict[str, Any] = Field(default_factory=dict)


class EntityCreate(EntityBase):
    type: EntityType
    # Characters only: whose sheet this is at the table. The account that may
    # edit it follows from the seat, so `owner_id` isn't taken from the client.
    player_id: uuid.UUID | None = None


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    visibility: Visibility | None = None
    data: dict[str, Any] | None = None
    image_url: str | None = Field(default=None, max_length=1024)
    # Characters only, DM only: hand the sheet to a different seat
    player_id: uuid.UUID | None = None


class EntitySummary(BaseModel):
    """The shape used in lists, search results and link panels."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: EntityType
    owner_id: uuid.UUID | None = None
    player_id: uuid.UUID | None = None
    name: str
    slug: str
    summary: str | None
    image_url: str | None
    visibility: Visibility
    tags: list[str]
    # Structured per-type fields (quest status, session number…) — small, and
    # lists need them to say anything useful about story state
    data: dict[str, Any] = Field(default_factory=dict)
    # Where it sits, when a list has been asked to say. Filled only by the
    # listing endpoint, which fetches every parent on the page in one query;
    # everywhere else this stays null rather than costing a join nobody wanted.
    parent: "EntityRef | None" = None


class LinkedEntity(EntitySummary):
    relation: LinkRelation


class EntityRead(EntitySummary):
    campaign_id: uuid.UUID
    body: str | None
    created_at: datetime
    updated_at: datetime


class EntityDetail(EntityRead):
    # How many other entities had their [[references]] rewritten by a rename
    rewritten_references: int = 0
    links: list[LinkedEntity] = Field(default_factory=list)
    backlinks: list[LinkedEntity] = Field(default_factory=list)
    # Where this sits in the world, outermost first — region, town, building.
    # Carried on the detail rather than fetched separately so a page can draw
    # its own breadcrumb without a second round trip and a visible flash.
    ancestors: list[EntitySummary] = Field(default_factory=list)
    # Names in [[…]] that don't match anything yet, so the UI can offer to
    # create them instead of silently dropping the reference
    unresolved_links: list[str] = Field(default_factory=list)


class FogMask(BaseModel):
    """What the party has uncovered, one bit per grid cell, base64'd.

    The bound on `mask` is generous rather than exact: it only has to stop a
    client from writing a novel into the entity's data, not to police a grid
    whose dimensions the DM's map decides.
    """

    w: int = Field(ge=1, le=512)
    h: int = Field(ge=1, le=512)
    mask: str = Field(max_length=100_000)


class FogUpdate(BaseModel):
    # Null clears it, which is how a map goes back to having no fog at all
    fog: FogMask | None = None


class EntityRef(BaseModel):
    """Just enough of an entity to name it and link to it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: EntityType


class SortOrder(StrEnum):
    """How a list is ordered. A closed set so a typo can't silently sort by name."""

    NAME = "name"
    UPDATED = "updated"
    CREATED = "created"


class EntityPage(BaseModel):
    items: list[EntitySummary]
    total: int
    page: int
    page_size: int


class SearchHit(EntitySummary):
    rank: float


class LinkCreate(BaseModel):
    to_id: uuid.UUID
    relation: LinkRelation = LinkRelation.RELATED_TO


class EntityImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_id: uuid.UUID
    url: str
    caption: str | None
    position: int


class EntityImageUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=300)
    position: int | None = Field(default=None, ge=0)


class CampaignImage(EntityImageRead):
    """A gallery image with just enough context to build a slideshow from."""

    entity_name: str
    entity_type: EntityType
