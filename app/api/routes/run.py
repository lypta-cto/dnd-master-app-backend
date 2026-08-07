import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.campaign_deps import DmCtx
from app.api.deps import SessionDep
from app.models.run import RunState
from app.schemas.run import RunRead, RunUpdate

router = APIRouter(prefix="/campaigns/{campaign_id}/run", tags=["run"])

# DM-only on both verbs. This is the screen behind the screen: which clue has
# actually been handed over, who hasn't spoken yet, what the clock is about to
# do. Players get the table's display, not this.


async def _state_for(session: SessionDep, campaign_id: uuid.UUID) -> RunState:
    state = (
        await session.execute(select(RunState).where(RunState.campaign_id == campaign_id))
    ).scalar_one_or_none()

    if state is None:
        state = RunState(campaign_id=campaign_id)
        session.add(state)
        await session.flush()

    return state


@router.get("", response_model=RunRead)
async def read_run(context: DmCtx, session: SessionDep) -> RunRead:
    state = await _state_for(session, context.campaign.id)
    return RunRead.model_validate(state)


@router.put("", response_model=RunRead)
async def set_run(payload: RunUpdate, context: DmCtx, session: SessionDep) -> RunRead:
    """Whole-state replace, like combat — one call per change at the table."""
    state = await _state_for(session, context.campaign.id)

    state.active = payload.active
    state.session_id = payload.session_id
    state.scene_id = payload.scene_id
    state.revealed = [str(clue_id) for clue_id in payload.revealed]
    state.spotlight = {str(player_id): count for player_id, count in payload.spotlight.items()}
    state.clock = [event.model_dump(mode="json") for event in payload.clock]
    state.notes = payload.notes

    await session.flush()
    await session.refresh(state)
    return RunRead.model_validate(state)
