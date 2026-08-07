"""
Avatar handling.

Uploads land on local disk and are served by the app. That's fine for one
machine — for anything horizontally scaled, swap `store_avatar` for an S3 / R2
put and return the public URL. Nothing else needs to change.
"""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

# Decoding is what makes this safe: a file that only claims to be an image
# fails here, so nothing unexpected ever reaches the disk.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
MAX_DIMENSION = 512


def _dir(folder: str) -> Path:
    path = Path(settings.UPLOAD_DIR) / folder
    path.mkdir(parents=True, exist_ok=True)
    return path


async def store_avatar(file: UploadFile, user_id: uuid.UUID) -> str:
    return await store_image(file, "avatars", user_id, max_dimension=MAX_DIMENSION)


async def store_entity_image(file: UploadFile, entity_id: uuid.UUID) -> str:
    # Entity art gets cast onto a TV, so it keeps far more resolution than an
    # avatar. An entity owns many images, so nothing is replaced on upload —
    # rows in entity_images own their files and are deleted one by one.
    return await store_image(
        file, "entities", entity_id, max_dimension=1600, replace_previous=False
    )


def delete_by_url(url: str) -> None:
    """Removes exactly the file a gallery row points at. Silently ignores URLs
    outside the upload tree (external art pasted in by hand)."""
    prefix = f"{settings.UPLOAD_URL_PREFIX}/"
    if not url.startswith(prefix):
        return

    relative = Path(url.removeprefix(prefix))
    target = (Path(settings.UPLOAD_DIR) / relative).resolve()

    # Refuse to step outside the upload dir, however mangled the stored URL is
    if Path(settings.UPLOAD_DIR).resolve() in target.parents:
        target.unlink(missing_ok=True)


async def store_image(
    file: UploadFile,
    folder: str,
    key: uuid.UUID,
    *,
    max_dimension: int,
    replace_previous: bool = True,
) -> str:
    """Validates, normalises and writes the image. Returns its public URL."""
    raw = await file.read()

    if len(raw) > settings.MAX_AVATAR_BYTES:
        limit_mb = settings.MAX_AVATAR_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image must be smaller than {limit_mb} MB",
        )

    from io import BytesIO

    try:
        image = Image.open(BytesIO(raw))
        image.verify()  # cheap structural check
        image = Image.open(BytesIO(raw))  # verify() exhausts the file object
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file is not a readable image",
        ) from exc

    if image.format not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format. Use {', '.join(sorted(ALLOWED_FORMATS))}.",
        )

    # Flatten transparency onto white — WebP keeps alpha, but a stray alpha
    # channel on a dark avatar reads as a hole in the UI.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
    else:
        image = image.convert("RGB")

    image.thumbnail((max_dimension, max_dimension))

    # New filename each time so caches and CDNs pick the change up immediately
    filename = f"{key}-{uuid.uuid4().hex[:8]}.webp"
    destination = _dir(folder) / filename

    if replace_previous:
        remove_previous(key, folder=folder, keep=filename)
    image.save(destination, format="WEBP", quality=85, method=4)

    return f"{settings.UPLOAD_URL_PREFIX}/{folder}/{filename}"


def remove_previous(key: uuid.UUID, folder: str = "avatars", keep: str | None = None) -> None:
    """Old files are dead weight — the URL is only ever stored on the owner row."""
    for existing in _dir(folder).glob(f"{key}-*.webp"):
        if existing.name != keep:
            existing.unlink(missing_ok=True)
