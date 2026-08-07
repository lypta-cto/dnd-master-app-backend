"""Seats at the table, and the thin bridge between a seat and an account.

A player exists whether or not anyone ever logs in. When an account does turn
up — invited by the DM, or registering with an address the DM invited earlier —
these helpers wire it to the seat and hand the person write access to their own
characters. Everything else in the app keeps talking about accounts only.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CampaignMember, CampaignRole
from app.models.entity import Entity, EntityType
from app.models.player import Player
from app.models.user import User


async def link_account(session: AsyncSession, player: Player, user: User) -> Player:
    """Give a seat an account: membership, ownership of its characters, done."""
    player.user_id = user.id
    player.invited_email = None

    member = (
        await session.execute(
            select(CampaignMember).where(
                CampaignMember.campaign_id == player.campaign_id,
                CampaignMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if member is None:
        session.add(
            CampaignMember(
                campaign_id=player.campaign_id,
                user_id=user.id,
                role=CampaignRole.PLAYER,
            )
        )

    # Sheets the DM already filled in become theirs to edit
    characters = (
        await session.execute(select(Entity).where(Entity.player_id == player.id))
    ).scalars()
    for character in characters:
        character.owner_id = user.id

    await session.flush()
    return player


async def claim_invitations(session: AsyncSession, user: User) -> list[Player]:
    """Called on registration: pick up any seats invited to this address."""
    invited = (
        (
            await session.execute(
                select(Player).where(
                    func.lower(Player.invited_email) == user.email.lower(),
                    Player.user_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    for player in invited:
        await link_account(session, player, user)

    return list(invited)


async def seat_for_user(
    session: AsyncSession, campaign_id: uuid.UUID, user_id: uuid.UUID
) -> Player | None:
    """The seat this account occupies in this campaign, if it has one."""
    return (
        await session.execute(
            select(Player).where(Player.campaign_id == campaign_id, Player.user_id == user_id)
        )
    ).scalar_one_or_none()


async def sync_character_owner(session: AsyncSession, entity: Entity) -> None:
    """Keep write access following the seat.

    `player_id` says whose character it is at the table; `owner_id` says which
    account may edit it. Assigning a character to a seat with an account grants
    that account access; moving it to a seat without one takes it away, which is
    what a DM taking a sheet back should do.
    """
    if entity.type is not EntityType.CHARACTER:
        return

    if entity.player_id is None:
        return

    player = await session.get(Player, entity.player_id)
    entity.owner_id = player.user_id if player else None
