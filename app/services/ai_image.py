"""Turning a description into a picture for the table.

Kept separate from `ai_text` because the two halves fail differently and are
priced differently — an image costs cents where a paragraph costs a fraction of
one, so quality and size are settings you actually want to turn down.

The prompt is built from what the DM already wrote — the entity's own summary
and body — because a picture that doesn't match the text on the page is worse
than no picture.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from io import BytesIO

import httpx
from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"

# What the DM picks between, in their words. "low" is not a warning label —
# with the prompt below it produces a perfectly usable table illustration, and
# it costs a quarter of what "medium" costs.
QUALITIES: dict[str, str] = {"draft": "low", "good": "medium"}

# Provider rates per million tokens, for showing the DM what a click cost.
# Two numbers in one place beat a guess in the UI; if they move, they move here.
# These are the mini model's rates — change them with IMAGE_MODEL or the price
# in the toast becomes a confident lie.
IMAGE_TOKEN_RATE = 8.0
TEXT_TOKEN_RATE = 2.0

# What the picture is for, per type — a portrait and a map want different
# framing. Every subject stands in a scene: the blank-backdrop versions came
# out looking like catalogue photography, and a world is the one thing a
# fantasy picture is for.
STYLES: dict[str, str] = {
    "npc": (
        "character portrait from the chest up, caught mid-thought in the place "
        "they belong — their room, street or wilderness alive behind them"
    ),
    "character": (
        "heroic character portrait from the chest up, in the place they belong, "
        "their world alive behind them"
    ),
    "monster": (
        "full-body creature in its own habitat, dynamic pose, dramatic low "
        "camera angle, the environment telling where it hunts"
    ),
    "location": "wide establishing shot of the place, no people in the foreground",
    "scene": "wide establishing shot, cinematic framing",
    "item": "single object study, moody light, a hint of the place it was found",
    "map": "top-down map illustration, clear landmarks, no text labels",
}

DEFAULT_STYLE = "illustration for a tabletop roleplaying game"


def configured() -> bool:
    return bool(settings.OPENAI_API_KEY)


def build_prompt(kind: str, name: str, description: str, extra: str | None) -> str:
    """The DM's own words first; style and medium after."""
    parts = [f"{name}. {description.strip()}"] if description.strip() else [name]

    if extra:
        parts.append(extra.strip())

    parts.append(STYLES.get(kind, DEFAULT_STYLE))
    # Two halves doing two jobs, both learned the hard way. The painterly half
    # is the look — asking for "digital illustration, balanced lighting" got
    # technically fine pictures of creatures floating on beige, like catalogue
    # photography. The sharpness half is the guard: an earlier prompt that led
    # with mood ("dramatic lighting, muted palette") came out soft and murky at
    # every price point, so the subject keeps its "crisp focus" and the paint
    # and atmosphere are pushed to the background layer, where blur is depth
    # rather than mush.
    # The first painterly draft of this prompt named its lighting ("golden
    # hour, torchlight") and invoked "classic rulebook art" — old varnished
    # paintings — and every image came back the same amber-brown regardless of
    # subject. The palette now follows the subject and nothing else names a
    # colour, with the sepia wash banned by name.
    parts.append(
        "Painterly high-fantasy concept art with confident visible brushwork, "
        "dramatic natural light that suits the scene, real atmosphere and "
        "depth. A full varied colour palette that follows the subject — cool "
        "blues and greens as readily as warm tones; never a monochrome sepia "
        "or amber wash over everything. The subject itself in crisp focus "
        "with clean readable shapes and a strong silhouette; the painted "
        "world behind it softer, so the scene has depth. "
        "No text, no lettering, no watermark."
    )

    return ". ".join(parts)


@dataclass(frozen=True)
class Generated:
    """The picture, and what it cost — the DM is spending real money per click."""

    raw: bytes
    cents: float


async def generate(prompt: str, quality: str | None = None) -> Generated:
    """Ask the provider for one image and hand back the bytes with its price."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image generation is off — set OPENAI_API_KEY to turn it on.",
        )

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                OPENAI_IMAGES_URL,
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": settings.IMAGE_MODEL,
                    "prompt": prompt[:4000],
                    "size": settings.IMAGE_SIZE,
                    "quality": QUALITIES.get(quality or "", settings.IMAGE_QUALITY),
                    "n": 1,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't reach the image provider.",
        ) from exc

    if response.status_code >= 400:
        # Surface the provider's own message — usually says what it disliked
        detail = response.json().get("error", {}).get("message", "Image generation failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    body = response.json()
    payload = body.get("data") or []

    if not payload or "b64_json" not in payload[0]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider returned nothing usable.",
        )

    # The provider bills the picture as tokens and reports them; using its own
    # count means the price shown is what was charged, not our estimate of it.
    usage = body.get("usage") or {}
    cents = (
        usage.get("output_tokens", 0) * IMAGE_TOKEN_RATE
        + usage.get("input_tokens", 0) * TEXT_TOKEN_RATE
    ) / 10_000

    try:
        return Generated(raw=base64.b64decode(payload[0]["b64_json"]), cents=round(cents, 2))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider returned something that isn't an image.",
        ) from exc


def store(raw: bytes, entity_id: uuid.UUID) -> str:
    """Normalise to WebP next to hand-uploaded art, and return its URL.

    Written here rather than reusing `media.store_image` because that one takes
    an UploadFile — this is bytes we already hold, and the validation it does
    (size, format, transparency) is the part worth repeating.
    """
    if len(raw) > settings.MAX_ENTITY_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The generated image came back too large to store.",
        )

    try:
        image = Image.open(BytesIO(raw))
        image.verify()
        image = Image.open(BytesIO(raw))
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider returned something that isn't an image.",
        ) from exc

    image = image.convert("RGB")
    image.thumbnail((settings.MAX_ENTITY_IMAGE_DIMENSION, settings.MAX_ENTITY_IMAGE_DIMENSION))

    filename = f"{entity_id}-{uuid.uuid4().hex[:8]}.webp"
    destination = settings.UPLOAD_DIR_PATH / "entities" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="WEBP", quality=85, method=4)

    return f"{settings.UPLOAD_URL_PREFIX}/entities/{filename}"
