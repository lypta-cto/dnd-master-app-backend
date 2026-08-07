import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select

from app.api.campaign_deps import CampaignCtx, DmCtx
from app.api.deps import SessionDep
from app.models.entity import Entity, EntityLink, EntityType, Visibility
from app.models.entity_image import EntityImage
from app.schemas.auth import MessageResponse
from app.schemas.entity import (
    CampaignImage,
    EntityCreate,
    EntityDetail,
    EntityImageRead,
    EntityImageUpdate,
    EntityPage,
    EntityRead,
    EntitySummary,
    EntityUpdate,
    LinkCreate,
    LinkedEntity,
    SearchHit,
)
from app.services import entities as entity_service
from app.services import media as media_service

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["entities"])


def _as_linked(rows) -> list[LinkedEntity]:
    # `relation` lives on the link row, not the entity, so the summary is built
    # first and the relation attached — model_validate alone would miss it.
    return [
        LinkedEntity(**EntitySummary.model_validate(entity).model_dump(), relation=relation)
        for entity, relation in rows
    ]


async def _detail(
    session: SessionDep,
    context: CampaignCtx,
    entity: Entity,
    unresolved: list[str] | None = None,
) -> EntityDetail:
    """One place that assembles an entity with both directions of its links."""
    links = await entity_service.outgoing_links(
        session, entity.id, is_dm=context.is_dm, user_id=context.user.id
    )
    backs = await entity_service.backlinks(
        session, entity.id, is_dm=context.is_dm, user_id=context.user.id
    )

    if unresolved is None:
        # Recompute rather than store: a name becomes resolvable the moment
        # someone creates the entity it refers to.
        resolved = {name.casefold() for name, _ in ((e.name, r) for e, r in links)}
        resolved |= {e.slug for e, _ in links}
        unresolved = [
            name
            for name in entity_service.extract_wiki_links(entity.body)
            if name.casefold() not in resolved
        ]

    return EntityDetail(
        **EntityRead.model_validate(entity).model_dump(),
        links=_as_linked(links),
        backlinks=_as_linked(backs),
        unresolved_links=unresolved,
    )


async def _load(session: SessionDep, context: CampaignCtx, entity_id: uuid.UUID) -> Entity:
    entity = await session.get(Entity, entity_id)

    if entity is None or entity.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # A player must not be able to confirm a secret exists by probing ids —
    # unless it's theirs: your own sheet is never a secret from you.
    if (
        not context.is_dm
        and entity.visibility is Visibility.DM_ONLY
        and entity.owner_id != context.user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return entity


def _can_write(context: CampaignCtx, entity: Entity) -> bool:
    """The DM writes everything; a player writes exactly their own character."""
    return context.is_dm or (
        entity.type is EntityType.CHARACTER and entity.owner_id == context.user.id
    )


async def _load_writable(
    session: SessionDep, context: CampaignCtx, entity_id: uuid.UUID
) -> Entity:
    """Load an entity the caller is allowed to change, or refuse."""
    entity = await _load(session, context, entity_id)

    if not _can_write(context, entity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the DM can change this",
        )

    return entity


@router.get("/search", response_model=list[SearchHit])
async def search_entities(
    context: CampaignCtx,
    session: SessionDep,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[SearchHit]:
    """One query across every type in the campaign."""
    hits = await entity_service.search(
        session, context.campaign.id, q, is_dm=context.is_dm, user_id=context.user.id, limit=limit
    )
    return [
        SearchHit(**EntitySummary.model_validate(entity).model_dump(), rank=rank)
        for entity, rank in hits
    ]


@router.get("/entities", response_model=EntityPage)
async def list_entities(
    context: CampaignCtx,
    session: SessionDep,
    type: EntityType | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> EntityPage:
    filters = [Entity.campaign_id == context.campaign.id]

    if type is not None:
        filters.append(Entity.type == type)
    if tag:
        filters.append(Entity.tags.any(tag))
    if (visible := entity_service.visibility_filter(context.is_dm, context.user.id)) is not None:
        filters.append(visible)

    total = await session.scalar(select(func.count()).select_from(Entity).where(*filters)) or 0

    result = await session.execute(
        select(Entity)
        .where(*filters)
        .order_by(Entity.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return EntityPage(
        items=[EntitySummary.model_validate(entity) for entity in result.scalars()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/entities", response_model=EntityDetail, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: EntityCreate, context: CampaignCtx, session: SessionDep
) -> EntityDetail:
    if not context.is_dm:
        # The one thing a player may create is their own character
        if payload.type is not EntityType.CHARACTER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Only the DM can do that"
            )
        payload.owner_id = context.user.id
        # A sheet the party can see; the DM can tighten it later if wanted
        payload.visibility = Visibility.SHARED

    entity = Entity(
        campaign_id=context.campaign.id,
        type=payload.type,
        owner_id=payload.owner_id if payload.type is EntityType.CHARACTER else None,
        name=payload.name,
        slug=await entity_service.unique_slug(session, context.campaign.id, payload.name),
        summary=payload.summary,
        body=payload.body,
        tags=payload.tags,
        data=payload.data,
        visibility=payload.visibility,
    )
    session.add(entity)
    await session.flush()

    _, unresolved = await entity_service.sync_wiki_links(session, entity)

    return await _detail(session, context, entity, unresolved)


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def read_entity(
    entity_id: uuid.UUID, context: CampaignCtx, session: SessionDep
) -> EntityDetail:
    entity = await _load(session, context, entity_id)
    return await _detail(session, context, entity)


@router.patch("/entities/{entity_id}", response_model=EntityDetail)
async def update_entity(
    entity_id: uuid.UUID,
    payload: EntityUpdate,
    context: CampaignCtx,
    session: SessionDep,
) -> EntityDetail:
    changes = payload.model_dump(exclude_unset=True)
    entity = await _load(session, context, entity_id)

    if not _can_write(context, entity):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the DM can do that"
        )

    # A player edits the sheet, not who gets to see it
    if not context.is_dm:
        changes.pop("visibility", None)

    rewritten = 0
    old_name = entity.name

    if "name" in changes and changes["name"] != entity.name:
        entity.slug = await entity_service.unique_slug(
            session, context.campaign.id, changes["name"], exclude_id=entity.id
        )

    for field, value in changes.items():
        setattr(entity, field, value)

    await session.flush()

    # A rename drags every [[Old Name]] in the campaign's prose along with it —
    # and reconnects prose that was already pointing at the new name.
    if "name" in changes and changes["name"] != old_name:
        rewritten = await entity_service.rewrite_references(
            session, context.campaign.id, old_name, entity.name, exclude_id=entity.id
        )
        await entity_service.resync_bodies_referencing(
            session, context.campaign.id, entity.name, exclude_id=entity.id
        )

    # Re-resolve on every save: renaming a target should reconnect the prose
    # that points at it, not leave a dangling reference.
    _, unresolved = await entity_service.sync_wiki_links(session, entity)
    await session.refresh(entity)

    detail = await _detail(session, context, entity, unresolved)
    detail.rewritten_references = rewritten
    return detail


@router.delete("/entities/{entity_id}", response_model=MessageResponse)
async def delete_entity(
    entity_id: uuid.UUID, context: DmCtx, session: SessionDep
) -> MessageResponse:
    entity = await _load(session, context, entity_id)
    await session.delete(entity)
    return MessageResponse(message="Deleted")


@router.post(
    "/entities/{entity_id}/links",
    response_model=EntityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_link(
    entity_id: uuid.UUID, payload: LinkCreate, context: DmCtx, session: SessionDep
) -> EntityRead:
    """An explicit typed relation, alongside the ones the prose creates."""
    entity = await _load(session, context, entity_id)
    target = await _load(session, context, payload.to_id)

    if entity.id == target.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="An entity can't link to itself"
        )

    exists = (
        await session.execute(
            select(EntityLink).where(
                EntityLink.from_id == entity.id,
                EntityLink.to_id == target.id,
                EntityLink.relation == payload.relation,
            )
        )
    ).scalar_one_or_none()

    if exists is None:
        session.add(
            EntityLink(from_id=entity.id, to_id=target.id, relation=payload.relation)
        )
        await session.flush()

    return EntityRead.model_validate(entity)


@router.delete("/entities/{entity_id}/links/{to_id}", response_model=MessageResponse)
async def delete_link(
    entity_id: uuid.UUID, to_id: uuid.UUID, context: DmCtx, session: SessionDep
) -> MessageResponse:
    entity = await _load(session, context, entity_id)

    result = await session.execute(
        select(EntityLink).where(EntityLink.from_id == entity.id, EntityLink.to_id == to_id)
    )
    removed = 0

    for link in result.scalars():
        await session.delete(link)
        removed += 1

    return MessageResponse(message=f"Removed {removed} link(s)")

# --- Gallery -----------------------------------------------------------------
#
# Many images per entity: the portrait, the battle art, the floor plan. Rows
# own their files — deleting one removes exactly that file. `Entity.image_url`
# remains the cover shown in lists, set from any gallery image.


@router.get("/images", response_model=list[CampaignImage])
async def list_campaign_images(context: CampaignCtx, session: SessionDep) -> list[CampaignImage]:
    """Every gallery image in the campaign — the slideshow builder's pool."""
    statement = (
        select(EntityImage, Entity.name, Entity.type)
        .join(Entity, Entity.id == EntityImage.entity_id)
        .where(Entity.campaign_id == context.campaign.id)
        .order_by(Entity.name, EntityImage.position, EntityImage.created_at)
    )

    if (visible := entity_service.visibility_filter(context.is_dm, context.user.id)) is not None:
        statement = statement.where(visible)

    return [
        CampaignImage(
            **EntityImageRead.model_validate(image).model_dump(),
            entity_name=name,
            entity_type=type_,
        )
        for image, name, type_ in (await session.execute(statement)).all()
    ]


@router.get("/entities/{entity_id}/images", response_model=list[EntityImageRead])
async def list_entity_images(
    entity_id: uuid.UUID, context: CampaignCtx, session: SessionDep
) -> list[EntityImageRead]:
    entity = await _load(session, context, entity_id)

    result = await session.execute(
        select(EntityImage)
        .where(EntityImage.entity_id == entity.id)
        .order_by(EntityImage.position, EntityImage.created_at)
    )
    return [EntityImageRead.model_validate(image) for image in result.scalars()]


@router.post(
    "/entities/{entity_id}/images",
    response_model=EntityImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_entity_image(
    entity_id: uuid.UUID,
    context: CampaignCtx,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    caption: Annotated[str | None, Form()] = None,
) -> EntityImageRead:
    entity = await _load_writable(session, context, entity_id)

    url = await media_service.store_entity_image(file, entity.id)

    last = await session.scalar(
        select(func.max(EntityImage.position)).where(EntityImage.entity_id == entity.id)
    )
    image = EntityImage(
        entity_id=entity.id,
        url=url,
        caption=caption[:300] if caption else None,
        position=(last if last is not None else -1) + 1,
    )
    session.add(image)

    # First image doubles as the cover, so lists stop showing a placeholder
    if not entity.image_url:
        entity.image_url = url

    await session.flush()
    await session.refresh(image)
    return EntityImageRead.model_validate(image)


@router.patch("/entities/{entity_id}/images/{image_id}", response_model=EntityImageRead)
async def update_entity_image(
    entity_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: EntityImageUpdate,
    context: CampaignCtx,
    session: SessionDep,
) -> EntityImageRead:
    await _load_writable(session, context, entity_id)
    image = await session.get(EntityImage, image_id)

    if image is None or image.entity_id != entity_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(image, field, value)

    await session.flush()
    await session.refresh(image)
    return EntityImageRead.model_validate(image)


@router.post("/entities/{entity_id}/images/{image_id}/cover", response_model=EntityRead)
async def set_cover_image(
    entity_id: uuid.UUID, image_id: uuid.UUID, context: CampaignCtx, session: SessionDep
) -> EntityRead:
    entity = await _load_writable(session, context, entity_id)
    image = await session.get(EntityImage, image_id)

    if image is None or image.entity_id != entity.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    entity.image_url = image.url
    await session.flush()
    await session.refresh(entity)
    return EntityRead.model_validate(entity)


@router.delete("/entities/{entity_id}/images/{image_id}", response_model=MessageResponse)
async def delete_entity_image_row(
    entity_id: uuid.UUID, image_id: uuid.UUID, context: CampaignCtx, session: SessionDep
) -> MessageResponse:
    entity = await _load_writable(session, context, entity_id)
    image = await session.get(EntityImage, image_id)

    if image is None or image.entity_id != entity.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    media_service.delete_by_url(image.url)

    # A cover that pointed at this image falls back to whatever remains
    if entity.image_url == image.url:
        replacement = await session.scalar(
            select(EntityImage.url)
            .where(EntityImage.entity_id == entity.id, EntityImage.id != image.id)
            .order_by(EntityImage.position)
            .limit(1)
        )
        entity.image_url = replacement

    await session.delete(image)
    return MessageResponse(message="Image removed")
