import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserRead

Experience = Literal["new", "some", "veteran"]
Preference = Literal["combat", "roleplay", "puzzles", "exploration"]


class PlayerBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Discord handle, phone, "Ana's brother" — whatever gets them to the table
    contact: str | None = Field(default=None, max_length=160)
    experience: Experience | None = None
    preferences: list[Preference] = Field(default_factory=list, max_length=4)
    notes: str | None = Field(default=None, max_length=1000)


class PlayerCreate(PlayerBase):
    pass


class PlayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=160)
    experience: Experience | None = None
    preferences: list[Preference] | None = Field(default=None, max_length=4)
    notes: str | None = Field(default=None, max_length=1000)


class PlayerCharacter(BaseModel):
    """Just enough of a sheet for the roster to be useful at a glance."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class PlayerRead(PlayerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    # Present once they accept an invitation; most seats never have one
    account: UserRead | None = None
    invited_email: str | None = None
    characters: list[PlayerCharacter] = Field(default_factory=list)


class PlayerInvite(BaseModel):
    email: EmailStr
