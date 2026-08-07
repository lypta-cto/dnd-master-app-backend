import uuid
from datetime import datetime
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
    # Characters only: which player's sheet this is (DM assigns; players get themselves)
    owner_id: uuid.UUID | None = None


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    visibility: Visibility | None = None
    data: dict[str, Any] | None = None
    image_url: str | None = Field(default=None, max_length=1024)


class EntitySummary(BaseModel):
    """The shape used in lists, search results and link panels."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: EntityType
    owner_id: uuid.UUID | None = None
    name: str
    slug: str
    summary: str | None
    image_url: str | None
    visibility: Visibility
    tags: list[str]
    # Structured per-type fields (quest status, session number…) — small, and
    # lists need them to say anything useful about story state
    data: dict[str, Any] = Field(default_factory=dict)


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
    # Names in [[…]] that don't match anything yet, so the UI can offer to
    # create them instead of silently dropping the reference
    unresolved_links: list[str] = Field(default_factory=list)


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
