from typing import Literal

from pydantic import BaseModel, Field

from app.models.entity import EntityType


class AiStatus(BaseModel):
    """Which halves are switched on — each needs its own key."""

    text: bool
    images: bool


class DraftRequest(BaseModel):
    type: EntityType
    name: str = Field(min_length=1, max_length=200)
    # What the DM already knows about it; the draft is built around this
    brief: str | None = Field(default=None, max_length=2000)
    use_campaign_context: bool = True


class DraftResponse(BaseModel):
    text: str


class IllustrateRequest(BaseModel):
    # Framing the description can't carry — "at night", "seen from the river"
    extra: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=300)


Kind = Literal["text", "images"]
