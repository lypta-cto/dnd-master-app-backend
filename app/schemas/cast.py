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

        if self.mode is CastMode.SLIDESHOW:
            images = self.payload.get("images")
            if not isinstance(images, list) or not images:
                raise ValueError("mode 'slideshow' requires a non-empty payload.images list")
            for image in images:
                if not isinstance(image, dict) or not image.get("image_url"):
                    raise ValueError("every slideshow image needs an image_url")

        return self


class CastRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mode: CastMode
    payload: dict[str, Any]


class CastStatus(CastRead):
    """What the DM's control panel shows — including whether the table's screen
    is actually connected, which is the first thing you want to know."""

    displays_connected: int
