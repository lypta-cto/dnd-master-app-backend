"""
Membership resolution.

Every campaign-scoped route needs the same two answers: may this person see
this campaign at all, and are they the DM? Doing it in a dependency keeps that
check off every handler — and makes it impossible to forget one.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.models.campaign import Campaign, CampaignMember, CampaignRole
from app.models.user import Role, User


@dataclass(slots=True)
class CampaignContext:
    campaign: Campaign
    user: User
    role: CampaignRole

    @property
    def is_dm(self) -> bool:
        return self.role is CampaignRole.DM


async def get_campaign_context(
    session: SessionDep,
    user: CurrentUser,
    campaign_id: Annotated[uuid.UUID, Path()],
) -> CampaignContext:
    campaign = await session.get(Campaign, campaign_id)

    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.owner_id == user.id:
        return CampaignContext(campaign=campaign, user=user, role=CampaignRole.DM)

    membership = (
        await session.execute(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if membership is None:
        # 404 rather than 403: a stranger shouldn't learn that this campaign exists
        if user.role.can(Role.ADMIN):
            return CampaignContext(campaign=campaign, user=user, role=CampaignRole.DM)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    return CampaignContext(campaign=campaign, user=user, role=membership.role)


CampaignCtx = Annotated[CampaignContext, Depends(get_campaign_context)]


async def require_dm(context: CampaignCtx) -> CampaignContext:
    if not context.is_dm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the DM can do that",
        )
    return context


DmCtx = Annotated[CampaignContext, Depends(require_dm)]
