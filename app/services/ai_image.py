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
from io import BytesIO

import httpx
from fastapi import HTTPException, status
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"

# What the picture is for, per type — a portrait and a map want different framing
STYLES: dict[str, str] = {
    "npc": "character portrait, head and shoulders, neutral background",
    "character": "character portrait, head and shoulders, neutral background",
    "monster": "creature illustration, full body, plain background",
    "location": "wide establishing shot of the place, no people in the foreground",
    "scene": "wide establishing shot, cinematic framing",
    "item": "single object study on a plain background",
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
    parts.append(
        "Painted fantasy illustration, dramatic lighting, muted palette. "
        "No text, no lettering, no watermarks, no borders."
    )

    return ". ".join(parts)


async def generate(prompt: str) -> bytes:
    """Ask the provider for one image and hand back raw bytes."""
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
                    "quality": settings.IMAGE_QUALITY,
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

    payload = response.json().get("data") or []

    if not payload or "b64_json" not in payload[0]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image provider returned nothing usable.",
        )

    try:
        return base64.b64decode(payload[0]["b64_json"])
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
