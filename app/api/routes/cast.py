import uuid

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.campaign_deps import CampaignCtx, DmCtx
from app.api.deps import SessionDep
from app.core.database import SessionLocal
from app.models.campaign import Campaign
from app.models.cast import CastState
from app.schemas.cast import CastRead, CastStatus, CastUpdate, InitiativeUpdate
from app.services import cast as cast_service

router = APIRouter(tags=["cast"])


async def _state_for(session, campaign_id: uuid.UUID) -> CastState:
    state = (
        await session.execute(select(CastState).where(CastState.campaign_id == campaign_id))
    ).scalar_one_or_none()

    if state is None:
        state = CastState(campaign_id=campaign_id)
        session.add(state)
        await session.flush()

    return state


# --- DM side -----------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/cast", response_model=CastStatus)
async def read_cast(context: CampaignCtx, session: SessionDep) -> CastStatus:
    state = await _state_for(session, context.campaign.id)

    return CastStatus(
        mode=state.mode,
        payload=state.payload,
        initiative=state.initiative,
        displays_connected=cast_service.subscriber_count(context.campaign.id),
    )


@router.put("/campaigns/{campaign_id}/cast/initiative", response_model=CastStatus)
async def set_initiative(
    payload: InitiativeUpdate, context: DmCtx, session: SessionDep
) -> CastStatus:
    """The strip above whatever else is showing.

    Its own endpoint because it has its own lifetime: it goes up when the fight
    starts and comes down when the fight ends, and everything cast in between —
    the battle map, a portrait, a dice roll — happens underneath it. Folding it
    into the cast payload would mean every one of those replaced it.
    """
    state = await _state_for(session, context.campaign.id)
    # An empty list clears the strip rather than leaving an empty box on the
    # wall — the fight is over, so the header goes with it.
    state.initiative = (
        {"round": payload.round, "entries": [e.model_dump() for e in payload.entries]}
        if payload.entries
        else {}
    )
    await session.flush()
    await session.commit()
    cast_service.publish(context.campaign.id)

    return CastStatus(
        mode=state.mode,
        payload=state.payload,
        initiative=state.initiative,
        displays_connected=cast_service.subscriber_count(context.campaign.id),
    )


@router.put("/campaigns/{campaign_id}/cast", response_model=CastStatus)
async def set_cast(payload: CastUpdate, context: DmCtx, session: SessionDep) -> CastStatus:
    """
    Push something to the table's screen.

    Casting is deliberately separate from visibility: showing an NPC portrait
    for a moment shouldn't permanently reveal the entity in the players' app.
    """
    state = await _state_for(session, context.campaign.id)
    state.mode = payload.mode
    state.payload = payload.payload
    await session.flush()

    # Commit before notifying, so a display that reacts instantly can't read
    # the old row
    await session.commit()
    cast_service.publish(context.campaign.id)

    return CastStatus(
        mode=state.mode,
        payload=state.payload,
        initiative=state.initiative,
        displays_connected=cast_service.subscriber_count(context.campaign.id),
    )


# --- Display side ------------------------------------------------------------
#
# No login: a TV isn't a person. The display token is a read-only, per-campaign,
# rotatable credential — see Campaign.display_token.


async def _campaign_for_token(session, campaign_id: uuid.UUID, token: str) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)

    if campaign is None or not token or campaign.display_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown display link")

    return campaign


@router.get("/cast/{campaign_id}", response_model=CastRead)
async def read_cast_public(
    campaign_id: uuid.UUID,
    session: SessionDep,
    t: str = Query(description="Display token"),
) -> CastRead:
    """The display's initial render, and what it re-reads after every event."""
    campaign = await _campaign_for_token(session, campaign_id, t)
    state = await _state_for(session, campaign.id)
    return CastRead(mode=state.mode, payload=state.payload, initiative=state.initiative)


@router.get("/cast/{campaign_id}/stream")
async def stream_cast(
    campaign_id: uuid.UUID,
    session: SessionDep,
    t: str = Query(description="Display token"),
) -> StreamingResponse:
    """
    Server-Sent Events, not a WebSocket: traffic only goes server → display, and
    EventSource reconnects on its own — which matters on the wifi you'll
    actually be using.

    The stream carries a nudge rather than the state itself, so the display
    always re-reads the authoritative row and can't drift.
    """
    await _campaign_for_token(session, campaign_id, t)

    async def events():
        # A fresh session: this generator outlives the request's own
        async with SessionLocal():
            async for frame in cast_service.subscribe(campaign_id):
                yield frame

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stops nginx from swallowing the stream
        },
    )
