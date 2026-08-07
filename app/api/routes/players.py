import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.campaign_deps import CampaignCtx, DmCtx
from app.api.deps import SessionDep
from app.models.entity import Entity
from app.models.player import Player
from app.schemas.auth import MessageResponse
from app.schemas.player import PlayerCreate, PlayerInvite, PlayerRead, PlayerUpdate
from app.schemas.user import UserRead
from app.services import auth as auth_service
from app.services import players as player_service

router = APIRouter(prefix="/campaigns/{campaign_id}/players", tags=["players"])


def _read(player: Player) -> PlayerRead:
    """The seat plus whatever account it has, which is usually none."""
    return PlayerRead.model_validate(player).model_copy(
        update={
            "account": UserRead.model_validate(player.user) if player.user else None,
        }
    )


async def _load(session: SessionDep, context: CampaignCtx, player_id: uuid.UUID) -> Player:
    player = await session.get(Player, player_id)

    if player is None or player.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    return player


@router.get("", response_model=list[PlayerRead])
async def list_players(context: CampaignCtx, session: SessionDep) -> list[PlayerRead]:
    """Everyone at this table. Players see the roster too — they know who's there."""
    result = await session.execute(
        select(Player).where(Player.campaign_id == context.campaign.id).order_by(Player.name)
    )
    return [_read(player) for player in result.scalars()]


@router.post("", response_model=PlayerRead, status_code=status.HTTP_201_CREATED)
async def create_player(payload: PlayerCreate, context: DmCtx, session: SessionDep) -> PlayerRead:
    player = Player(campaign_id=context.campaign.id, **payload.model_dump())
    session.add(player)
    await session.flush()
    await session.refresh(player)
    return _read(player)


@router.patch("/{player_id}", response_model=PlayerRead)
async def update_player(
    player_id: uuid.UUID, payload: PlayerUpdate, context: CampaignCtx, session: SessionDep
) -> PlayerRead:
    player = await _load(session, context, player_id)

    # The DM keeps the roster; a player may still correct their own row
    if not context.is_dm and player.user_id != context.user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the DM can do that")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(player, field, value)

    await session.flush()
    await session.refresh(player)
    return _read(player)


@router.delete("/{player_id}", response_model=MessageResponse)
async def delete_player(
    player_id: uuid.UUID, context: DmCtx, session: SessionDep
) -> MessageResponse:
    """Remove the seat. Characters stay — the story keeps them either way."""
    player = await _load(session, context, player_id)

    characters = (
        await session.execute(select(Entity).where(Entity.player_id == player.id))
    ).scalars()
    for character in characters:
        character.player_id = None
        character.owner_id = None

    await session.delete(player)
    return MessageResponse(message="Player removed")


@router.post("/{player_id}/invite", response_model=PlayerRead)
async def invite_player(
    player_id: uuid.UUID, payload: PlayerInvite, context: DmCtx, session: SessionDep
) -> PlayerRead:
    """Offer this seat an account.

    If they already have one, they're in immediately. If not, the address is
    remembered and registering with it claims the seat — so the DM never waits
    on anybody to finish setting up.
    """
    player = await _load(session, context, player_id)

    if player.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This player already has an account"
        )

    user = await auth_service.get_user_by_email(session, payload.email)

    if user is not None:
        taken = (
            await session.execute(
                select(Player).where(
                    Player.campaign_id == context.campaign.id, Player.user_id == user.id
                )
            )
        ).scalar_one_or_none()

        if taken is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"That account already plays here as {taken.name}",
            )

        await player_service.link_account(session, player, user)
    else:
        player.invited_email = payload.email

    await session.flush()
    await session.refresh(player)
    return _read(player)
