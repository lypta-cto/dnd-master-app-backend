import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.campaign_deps import DmCtx
from app.api.deps import SessionDep
from app.models.coin import CoinEntry, CoinEntryType
from app.models.entity import Entity
from app.models.entity_image import EntityImage
from app.schemas.ai import (
    AiStatus,
    BilledRead,
    CoinEntryRead,
    DraftRequest,
    DraftResponse,
    IllustratedImage,
    IllustrateRequest,
    Purse,
    TopUpRequest,
)
from app.schemas.entity import EntityImageRead
from app.services import ai_image as image_service
from app.services import ai_text as text_service
from app.services import coins as coin_service
from app.services import openai_costs as billing

router = APIRouter(prefix="/campaigns/{campaign_id}/ai", tags=["ai"])

# DM-only throughout. Drafting is prep, and prep is the DM's side of the screen.


@router.get("", response_model=AiStatus)
async def read_status(context: DmCtx) -> AiStatus:
    """So the UI can hide what isn't switched on rather than failing on click."""
    return AiStatus(text=text_service.configured(), images=image_service.configured())


@router.get("/purse", response_model=Purse)
async def read_purse(context: DmCtx, session: SessionDep) -> Purse:
    """What this campaign has spent on generation, in coins.

    Cents are a bad unit for a running total — an illustration is under one and
    a draft is a fiftieth of one, so the number that matters never moves. Coins
    are sized so the cheapest thing the app does still costs more than one.
    """
    totals = await coin_service.summary(session, context.campaign.id)

    recent = (
        (
            await session.execute(
                select(CoinEntry)
                .where(CoinEntry.campaign_id == context.campaign.id)
                .order_by(CoinEntry.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    return Purse(
        balance=coin_service.coins(totals["balance"]),
        added=coin_service.coins(totals["added"]),
        spent_on_text=coin_service.coins(totals["text"]),
        spent_on_images=coin_service.coins(totals["image"]),
        spent_usd=round((totals["text"] + totals["image"]) / 1_000_000, 4),
        coins_per_dollar=coin_service.COINS_PER_DOLLAR,
        can_reconcile=billing.configured(),
        entries=[
            CoinEntryRead(
                id=entry.id,
                entry_type=entry.entry_type,
                coins=coin_service.coins(entry.micros),
                detail=entry.detail,
                created_at=entry.created_at,
            )
            for entry in recent
        ],
    )


@router.post("/purse/topup", response_model=Purse, status_code=status.HTTP_201_CREATED)
async def top_up(payload: TopUpRequest, context: DmCtx, session: SessionDep) -> Purse:
    """Record money put on the provider account, in dollars, as coins.

    Nothing is charged here — the app can't take payment and doesn't pretend
    to. This is the DM writing down what they already paid OpenAI, so the
    balance means something to count down from.
    """
    await coin_service.record(
        session,
        campaign_id=context.campaign.id,
        user_id=context.user.id,
        entry_type=CoinEntryType.TOPUP,
        micros=round(payload.usd * 1_000_000),
        detail=f"Added ${payload.usd:.2f}",
    )
    await session.flush()

    return await read_purse(context, session)


@router.get("/purse/billed", response_model=BilledRead)
async def read_billed(context: DmCtx, days: int = 30) -> BilledRead:
    """What OpenAI says the account was actually billed, for comparison.

    Two caveats worth keeping in front of whoever reads it. This is the whole
    organisation, not this campaign — anything else on the same OpenAI account
    is in the figure. And it is spending, not the balance left: OpenAI
    publishes no endpoint for the balance at all.
    """
    return BilledRead(**await billing.spent_since(days))


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
async def draft_description(
    payload: DraftRequest, context: DmCtx, session: SessionDep
) -> DraftResponse:
    """A first draft for the DM to rewrite. The prose isn't saved; the cost is."""
    drafted = await text_service.draft(
        kind=payload.type,
        name=payload.name,
        brief=payload.brief,
        context=_campaign_context(context) if payload.use_campaign_context else None,
        facts=payload.facts,
    )

    await coin_service.record(
        session,
        campaign_id=context.campaign.id,
        user_id=context.user.id,
        entry_type=CoinEntryType.TEXT,
        micros=-coin_service.micros_from_cents(drafted.cents),
        detail=f"Drafted {payload.name}",
    )

    return DraftResponse(text=drafted.text, cents=drafted.cents)


@router.post(
    "/entities/{entity_id}/illustrate",
    response_model=IllustratedImage,
    status_code=status.HTTP_201_CREATED,
)
async def illustrate_entity(
    entity_id: uuid.UUID,
    payload: IllustrateRequest,
    context: DmCtx,
    session: SessionDep,
) -> IllustratedImage:
    """Draw what's already written, and file it in the entity's gallery.

    The prompt comes from the entity's own summary and body — an illustration
    that contradicts the page is worse than none — and the result lands as an
    ordinary gallery image, so cover, caption, reorder and delete all work on it
    exactly as on anything the DM uploaded.
    """
    entity = await session.get(Entity, entity_id)

    if entity is None or entity.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # The type's own fields go in too. A kobold beggar was coming back drawn as
    # a cheerful human innkeeper, because race and occupation were sitting in
    # `data` and only the prose ever reached the model. `describe_facts` drops
    # the `dm_` keys, so the twist doesn't end up in a picture the party sees.
    facts = text_service.describe_facts(
        {
            key: str(value)
            for key, value in entity.data.items()
            if isinstance(value, str | int | float)
        }
    )

    description = " ".join(
        part for part in (entity.summary, facts, entity.body) if part
    ).strip()

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

    drawn = await image_service.generate(prompt, quality=payload.quality)
    url = image_service.store(drawn.raw, entity.id)

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

    await coin_service.record(
        session,
        campaign_id=context.campaign.id,
        user_id=context.user.id,
        entry_type=CoinEntryType.IMAGE,
        micros=-coin_service.micros_from_cents(drawn.cents),
        detail=f"Illustrated {entity.name} ({payload.quality})",
    )

    await session.flush()
    await session.refresh(image)
    return IllustratedImage(**EntityImageRead.model_validate(image).model_dump(), cents=drawn.cents)
