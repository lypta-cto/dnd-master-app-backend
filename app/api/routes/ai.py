import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.campaign_deps import DmCtx
from app.api.deps import SessionDep
from app.models.entity import Entity
from app.models.entity_image import EntityImage
from app.schemas.ai import AiStatus, DraftRequest, DraftResponse, IllustrateRequest
from app.schemas.entity import EntityImageRead
from app.services import ai_image as image_service
from app.services import ai_text as text_service

router = APIRouter(prefix="/campaigns/{campaign_id}/ai", tags=["ai"])

# DM-only throughout. Drafting is prep, and prep is the DM's side of the screen.


@router.get("", response_model=AiStatus)
async def read_status(context: DmCtx) -> AiStatus:
    """So the UI can hide what isn't switched on rather than failing on click."""
    return AiStatus(text=text_service.configured(), images=image_service.configured())


def _campaign_context(context: DmCtx) -> str | None:
    """Premise and tone, so a draft sounds like this campaign and not fantasy in general."""
    data = context.campaign.data
    bits = [
        context.campaign.summary,
        data.get("premise"),
        f"Tone: {data['tone']}." if data.get("tone") else None,
        f"Genre: {data['genre']}." if data.get("genre") else None,
    ]
    joined = " ".join(str(bit).strip() for bit in bits if bit)
    return joined[:1200] or None


@router.post("/draft", response_model=DraftResponse)
async def draft_description(payload: DraftRequest, context: DmCtx) -> DraftResponse:
    """A first draft for the DM to rewrite. Nothing is saved here."""
    text = await text_service.draft(
        kind=payload.type,
        name=payload.name,
        brief=payload.brief,
        context=_campaign_context(context) if payload.use_campaign_context else None,
    )
    return DraftResponse(text=text)


@router.post(
    "/entities/{entity_id}/illustrate",
    response_model=EntityImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def illustrate_entity(
    entity_id: uuid.UUID,
    payload: IllustrateRequest,
    context: DmCtx,
    session: SessionDep,
) -> EntityImageRead:
    """Draw what's already written, and file it in the entity's gallery.

    The prompt comes from the entity's own summary and body — an illustration
    that contradicts the page is worse than none — and the result lands as an
    ordinary gallery image, so cover, caption, reorder and delete all work on it
    exactly as on anything the DM uploaded.
    """
    entity = await session.get(Entity, entity_id)

    if entity is None or entity.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    description = " ".join(part for part in (entity.summary, entity.body) if part).strip()

    if not description and not payload.extra:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Write a description first — the picture is drawn from it.",
        )

    prompt = image_service.build_prompt(
        kind=entity.type.value,
        name=entity.name,
        description=description[:2000],
        extra=payload.extra,
    )

    url = image_service.store(await image_service.generate(prompt), entity.id)

    last = await session.scalar(
        select(func.max(EntityImage.position)).where(EntityImage.entity_id == entity.id)
    )
    image = EntityImage(
        entity_id=entity.id,
        url=url,
        caption=payload.caption,
        position=(last if last is not None else -1) + 1,
    )
    session.add(image)

    if not entity.image_url:
        entity.image_url = url

    await session.flush()
    await session.refresh(image)
    return EntityImageRead.model_validate(image)
