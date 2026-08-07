from typing import Literal

from pydantic import BaseModel, Field

from app.models.entity import EntityType
from app.schemas.entity import EntityImageRead


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
    # Cheap by default: a draft is good enough for most things on the page, and
    # the DM asks for the expensive one when the picture is worth it.
    quality: Literal["draft", "good"] = "draft"


class IllustratedImage(EntityImageRead):
    """An ordinary gallery image, plus what it cost to draw."""

    cents: float


Kind = Literal["text", "images"]
