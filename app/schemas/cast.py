from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.cast import CastMode


class CastUpdate(BaseModel):
    """
    `payload` is validated against `mode`, because a display that receives
    `mode: image` with no `image_url` has nothing to render and the DM finds out
    in front of the table.
    """

    mode: CastMode
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_payload(self) -> "CastUpdate":
        required: dict[CastMode, tuple[str, ...]] = {
            CastMode.IMAGE: ("image_url",),
            CastMode.TEXT: ("text",),
        }

        for field in required.get(self.mode, ()):
            if not self.payload.get(field):
                raise ValueError(f"mode '{self.mode.value}' requires payload.{field}")

        if self.mode is CastMode.DICE:
            if not isinstance(self.payload.get("total"), int):
                raise ValueError("mode 'dice' requires an integer payload.total")
            rolls = self.payload.get("rolls")
            if not isinstance(rolls, list) or not all(isinstance(r, int) for r in rolls):
                raise ValueError("mode 'dice' requires payload.rolls as a list of integers")

        if self.mode is CastMode.SLIDESHOW:
            images = self.payload.get("images")
            if not isinstance(images, list) or not images:
                raise ValueError("mode 'slideshow' requires a non-empty payload.images list")
            for image in images:
                if not isinstance(image, dict) or not image.get("image_url"):
                    raise ValueError("every slideshow image needs an image_url")

        return self


class InitiativeEntry(BaseModel):
    """One name in the strip. What the table may know and nothing else — no
    hit points, no conditions, just who is up and who is down."""

    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="custom", max_length=20)
    down: bool = False
    active: bool = False
    # A face is fine for the table to see — it's the picture the party is
    # already looking at on the board
    image_url: str | None = Field(default=None, max_length=500)


class InitiativeUpdate(BaseModel):
    """Empty clears it. Kept apart from a cast so the strip survives one."""

    entries: list[InitiativeEntry] = Field(default_factory=list, max_length=60)
    round: int = Field(default=1, ge=1, le=999)


class CastRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mode: CastMode
    payload: dict[str, Any]
    # Rides above whatever `mode` is showing, and is not replaced by a cast
    initiative: dict[str, Any] = Field(default_factory=dict)


class CastStatus(CastRead):
    """What the DM's control panel shows — including whether the table's screen
    is actually connected, which is the first thing you want to know."""

    displays_connected: int
