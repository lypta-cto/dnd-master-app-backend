import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.campaign_deps import DmCtx
from app.api.deps import SessionDep
from app.models.combat import CombatState
from app.schemas.combat import CombatRead, CombatUpdate

router = APIRouter(prefix="/campaigns/{campaign_id}/combat", tags=["combat"])

# DM-only on both verbs: the fight is the DM's screen. The table sees only
# what gets cast — the sanitised `initiative` payload on the cast channel.


async def _state_for(session: SessionDep, campaign_id: uuid.UUID) -> CombatState:
    state = (
        await session.execute(
            select(CombatState).where(CombatState.campaign_id == campaign_id)
        )
    ).scalar_one_or_none()

    if state is None:
        state = CombatState(campaign_id=campaign_id)
        session.add(state)
        await session.flush()

    return state


@router.get("", response_model=CombatRead)
async def read_combat(context: DmCtx, session: SessionDep) -> CombatRead:
    state = await _state_for(session, context.campaign.id)
    return CombatRead.model_validate(state)


@router.put("", response_model=CombatRead)
async def set_combat(payload: CombatUpdate, context: DmCtx, session: SessionDep) -> CombatRead:
    """Whole-state replace — one call per change, matching the table's pace."""
    state = await _state_for(session, context.campaign.id)

    state.active = payload.active
    state.round = payload.round
    state.turn_index = payload.turn_index
    state.combatants = [c.model_dump(mode="json") for c in payload.combatants]

    await session.flush()
    await session.refresh(state)
    return CombatRead.model_validate(state)
