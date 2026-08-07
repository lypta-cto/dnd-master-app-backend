import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.campaign import CampaignRole
from app.schemas.user import UserRead


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    summary: str | None = Field(default=None, max_length=500)
    # Setup: type, system, tone, premise… and the `dm_` half nobody else sees
    data: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = Field(default=None, max_length=500)
    data: dict[str, Any] | None = None


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    summary: str | None
    owner_id: uuid.UUID
    created_at: datetime
    # `dm_` keys are removed before this leaves the API for a player
    data: dict[str, Any] = Field(default_factory=dict)

    # Filled in per request — what *you* are in this campaign
    my_role: CampaignRole | None = None


class CampaignDetail(CampaignRead):
    """Adds the things only a DM needs, so the list stays cheap."""

    display_token: str | None = None
    entity_count: int = 0


class MemberInvite(BaseModel):
    email: EmailStr
    role: CampaignRole = CampaignRole.PLAYER


class MemberUpdate(BaseModel):
    role: CampaignRole


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: CampaignRole
    user: UserRead
