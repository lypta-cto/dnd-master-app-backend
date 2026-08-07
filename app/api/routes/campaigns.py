import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_, select

from app.api.campaign_deps import CampaignCtx, DmCtx
from app.api.deps import CurrentUser, SessionDep
from app.models.campaign import Campaign, CampaignMember, CampaignRole, new_display_token
from app.models.entity import Entity
from app.schemas.auth import MessageResponse
from app.schemas.campaign import (
    CampaignCreate,
    CampaignDetail,
    CampaignRead,
    CampaignUpdate,
    MemberInvite,
    MemberRead,
    MemberUpdate,
)
from app.schemas.user import UserRead
from app.services import auth as auth_service
from app.services.entities import slugify

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


async def _unique_campaign_slug(session: SessionDep, name: str) -> str:
    base = slugify(name)
    candidate, suffix = base, 2

    while (
        await session.execute(select(Campaign.id).where(Campaign.slug == candidate).limit(1))
    ).scalar_one_or_none() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1

    return candidate


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(session: SessionDep, user: CurrentUser) -> list[CampaignRead]:
    """Campaigns you own or belong to."""
    result = await session.execute(
        select(Campaign)
        .outerjoin(CampaignMember, CampaignMember.campaign_id == Campaign.id)
        .where(or_(Campaign.owner_id == user.id, CampaignMember.user_id == user.id))
        .distinct()
        .order_by(Campaign.created_at.desc())
    )
    campaigns = list(result.scalars())

    roles = {
        row.campaign_id: row.role
        for row in (
            await session.execute(select(CampaignMember).where(CampaignMember.user_id == user.id))
        ).scalars()
    }

    return [
        CampaignRead.model_validate(campaign).model_copy(
            update={
                "my_role": CampaignRole.DM
                if campaign.owner_id == user.id
                else roles.get(campaign.id)
            }
        )
        for campaign in campaigns
    ]


@router.post("", response_model=CampaignDetail, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate, session: SessionDep, user: CurrentUser
) -> CampaignDetail:
    campaign = Campaign(
        name=payload.name,
        slug=await _unique_campaign_slug(session, payload.name),
        summary=payload.summary,
        owner_id=user.id,
        display_token=new_display_token(),
    )
    session.add(campaign)
    await session.flush()

    # The owner is also a member, so member lists don't have to special-case them
    session.add(CampaignMember(campaign_id=campaign.id, user_id=user.id, role=CampaignRole.DM))
    await session.flush()

    return CampaignDetail.model_validate(campaign).model_copy(
        update={"my_role": CampaignRole.DM, "display_token": campaign.display_token}
    )


@router.get("/{campaign_id}", response_model=CampaignDetail)
async def read_campaign(context: CampaignCtx, session: SessionDep) -> CampaignDetail:
    count = await session.scalar(
        select(func.count()).select_from(Entity).where(Entity.campaign_id == context.campaign.id)
    )

    return CampaignDetail.model_validate(context.campaign).model_copy(
        update={
            "my_role": context.role,
            "entity_count": count or 0,
            # The display token is a credential — DMs only
            "display_token": context.campaign.display_token if context.is_dm else None,
        }
    )


@router.patch("/{campaign_id}", response_model=CampaignDetail)
async def update_campaign(
    payload: CampaignUpdate, context: DmCtx, session: SessionDep
) -> CampaignDetail:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(context.campaign, field, value)

    await session.flush()
    return CampaignDetail.model_validate(context.campaign).model_copy(
        update={"my_role": context.role, "display_token": context.campaign.display_token}
    )


@router.delete("/{campaign_id}", response_model=MessageResponse)
async def delete_campaign(context: DmCtx, session: SessionDep) -> MessageResponse:
    if context.campaign.owner_id != context.user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can delete a campaign",
        )

    await session.delete(context.campaign)
    return MessageResponse(message="Campaign deleted")


@router.post("/{campaign_id}/display-token", response_model=CampaignDetail)
async def rotate_display_token(context: DmCtx, session: SessionDep) -> CampaignDetail:
    """Use after sharing a screen somewhere you'd rather not have shared it."""
    context.campaign.display_token = new_display_token()
    await session.flush()

    return CampaignDetail.model_validate(context.campaign).model_copy(
        update={"my_role": context.role, "display_token": context.campaign.display_token}
    )


# --- Members -----------------------------------------------------------------


@router.get("/{campaign_id}/members", response_model=list[MemberRead])
async def list_members(context: CampaignCtx, session: SessionDep) -> list[MemberRead]:
    result = await session.execute(
        select(CampaignMember).where(CampaignMember.campaign_id == context.campaign.id)
    )
    return [MemberRead.model_validate(member) for member in result.scalars()]


@router.post(
    "/{campaign_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED
)
async def invite_member(payload: MemberInvite, context: DmCtx, session: SessionDep) -> MemberRead:
    user = await auth_service.get_user_by_email(session, payload.email)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account with that email. They need to register first.",
        )

    existing = (
        await session.execute(
            select(CampaignMember).where(
                CampaignMember.campaign_id == context.campaign.id,
                CampaignMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already a member of this campaign"
        )

    member = CampaignMember(campaign_id=context.campaign.id, user_id=user.id, role=payload.role)
    session.add(member)
    await session.flush()

    return MemberRead(id=member.id, role=member.role, user=UserRead.model_validate(user))


@router.patch("/{campaign_id}/members/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: uuid.UUID, payload: MemberUpdate, context: DmCtx, session: SessionDep
) -> MemberRead:
    member = await session.get(CampaignMember, member_id)

    if member is None or member.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.user_id == context.campaign.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The owner's role can't be changed",
        )

    member.role = payload.role
    await session.flush()
    return MemberRead.model_validate(member)


@router.delete("/{campaign_id}/members/{member_id}", response_model=MessageResponse)
async def remove_member(
    member_id: uuid.UUID, context: DmCtx, session: SessionDep
) -> MessageResponse:
    member = await session.get(CampaignMember, member_id)

    if member is None or member.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.user_id == context.campaign.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The owner can't be removed"
        )

    await session.delete(member)
    return MessageResponse(message="Member removed")
