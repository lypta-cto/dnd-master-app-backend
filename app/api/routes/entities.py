import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select

from app.api.campaign_deps import CampaignCtx, DmCtx
from app.api.deps import SessionDep
from app.models.entity import Entity, EntityLink, EntityType, LinkRelation, Visibility
from app.models.entity_image import EntityImage
from app.models.player import Player
from app.schemas.auth import MessageResponse
from app.schemas.entity import (
    CampaignImage,
    EntityBulkCreate,
    EntityBulkResult,
    EntityCreate,
    EntityDetail,
    EntityImageRead,
    EntityImageUpdate,
    EntityPage,
    EntityRead,
    EntityRef,
    EntitySummary,
    EntityUpdate,
    FogUpdate,
    LinkCreate,
    LinkedEntity,
    SearchHit,
    SortOrder,
)
from app.services import entities as entity_service
from app.services import media as media_service
from app.services import players as player_service

router = APIRouter(prefix="/campaigns/{campaign_id}", tags=["entities"])


def _summary(entity: Entity, is_dm: bool) -> EntitySummary:
    """The only way an entity should reach a client — `dm_` fields filtered."""
    return EntitySummary.model_validate(entity).model_copy(
        update={"data": entity_service.visible_data(entity.data, is_dm)}
    )


def _as_linked(rows, is_dm: bool) -> list[LinkedEntity]:
    # `relation` lives on the link row, not the entity, so the summary is built
    # first and the relation attached — model_validate alone would miss it.
    return [
        LinkedEntity(**_summary(entity, is_dm).model_dump(), relation=relation)
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

    above = await entity_service.ancestors(
        session, entity.id, is_dm=context.is_dm, user_id=context.user.id
    )

    return EntityDetail(
        **EntityRead.model_validate(entity)
        .model_copy(update={"data": entity_service.visible_data(entity.data, context.is_dm)})
        .model_dump(),
        links=_as_linked(links, context.is_dm),
        backlinks=_as_linked(backs, context.is_dm),
        ancestors=[_summary(parent, context.is_dm) for parent in above],
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


async def _require_seat(session: SessionDep, context: CampaignCtx, player_id: uuid.UUID) -> Player:
    """A sheet can only be handed to a seat at this table."""
    player = await session.get(Player, player_id)

    if player is None or player.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    return player


async def _load_writable(session: SessionDep, context: CampaignCtx, entity_id: uuid.UUID) -> Entity:
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
        SearchHit(**_summary(entity, context.is_dm).model_dump(), rank=rank)
        for entity, rank in hits
    ]


@router.get("/entities", response_model=EntityPage)
async def list_entities(
    context: CampaignCtx,
    session: SessionDep,
    type: EntityType | None = None,
    tag: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    favorite: bool | None = None,
    sort: SortOrder = SortOrder.NAME,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> EntityPage:
    filters = [Entity.campaign_id == context.campaign.id]

    if type is not None:
        filters.append(Entity.type == type)
    if tag:
        filters.append(Entity.tags.any(tag))
    if favorite:
        # The starred working set out of an imported pile of hundreds —
        # a data flag rather than a column, like everything type-specific
        filters.append(Entity.data["favorite"].as_boolean().is_(True))
    if (needle := (q or "").strip()):
        # Filtering, not ranked search — /search already does that across the
        # campaign. Here the DM is looking down one list for a name they half
        # remember, so a plain contains over name and summary is what fits, and
        # it runs over the whole list rather than the page they can see.
        # Folded on both sides: a DM hunting "Kovač" in a list of two hundred
        # types "kovac", and a search that answers "no matches" to a name
        # plainly on the page reads as broken.
        pattern = func.unaccent(f"%{needle}%")
        filters.append(
            or_(
                func.unaccent(Entity.name).ilike(pattern),
                func.unaccent(Entity.summary).ilike(pattern),
            )
        )
    if (visible := entity_service.visibility_filter(context.is_dm, context.user.id)) is not None:
        filters.append(visible)

    total = await session.scalar(select(func.count()).select_from(Entity).where(*filters)) or 0

    # Name is the default because it's the only order you can predict; the
    # others are for "what was I working on" and "what did I just add".
    order = {
        SortOrder.NAME: Entity.name.asc(),
        SortOrder.UPDATED: Entity.updated_at.desc(),
        SortOrder.CREATED: Entity.created_at.desc(),
    }[sort]

    result = await session.execute(
        select(Entity)
        .where(*filters)
        # Ties need a tie-break or pagination lies. `now()` in Postgres is the
        # transaction's start time, so everything written by one request — the
        # sixteen entries of the starter pack, say — shares a timestamp to the
        # microsecond. Without a total order the database may answer the same
        # query differently each time, and a row shows up on two pages or none.
        .order_by(order, Entity.name.asc(), Entity.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    rows = list(result.scalars())

    # One query for the whole page rather than one per row: a list grouped by
    # where things happen is the point of having a world, and asking per scene
    # looks fine on a test campaign and falls over on a real one.
    parents = await entity_service.parents_of(
        session, [row.id for row in rows], is_dm=context.is_dm, user_id=context.user.id
    )

    items = []
    for entity in rows:
        summary = _summary(entity, context.is_dm)
        if (parent := parents.get(entity.id)) is not None:
            summary = summary.model_copy(update={"parent": EntityRef.model_validate(parent)})
        items.append(summary)

    return EntityPage(items=items, total=total, page=page, page_size=page_size)


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
        # Their own seat, whatever the request asked for
        seat = await player_service.seat_for_user(session, context.campaign.id, context.user.id)
        payload.player_id = seat.id if seat else None
        # A sheet the party can see; the DM can tighten it later if wanted
        payload.visibility = Visibility.SHARED

    is_character = payload.type is EntityType.CHARACTER
    seat = (
        await _require_seat(session, context, payload.player_id)
        if is_character and payload.player_id is not None
        else None
    )

    # Resolved before the insert so the row lands complete in one statement.
    # A seat without an account owns nothing; a player creating a sheet keeps it
    # either way, seat or no seat.
    owner_id = seat.user_id if seat else None
    if not context.is_dm and owner_id is None:
        owner_id = context.user.id

    entity = Entity(
        campaign_id=context.campaign.id,
        type=payload.type,
        player_id=seat.id if seat else None,
        owner_id=owner_id if is_character else None,
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


@router.post(
    "/entities/bulk", response_model=EntityBulkResult, status_code=status.HTTP_201_CREATED
)
async def create_entities_bulk(
    payload: EntityBulkCreate, context: DmCtx, session: SessionDep
) -> EntityBulkResult:
    """A bestiary import, in one round trip.

    Slugs are resolved against one upfront read of the campaign's slugs rather
    than a query per row — the per-entity path would ask the database eight
    hundred questions it can answer once. Wiki-link syncing is skipped on
    purpose: imported statblocks don't carry [[links]], and parsing 800 bodies
    to find that out would be the slowest no-op in the app.
    """
    taken = set(
        (
            await session.execute(
                select(Entity.slug).where(Entity.campaign_id == context.campaign.id)
            )
        ).scalars()
    )

    created = 0
    skipped = 0

    for item in payload.entities:
        base = entity_service.slugify(item.name)

        if payload.skip_existing and base in taken:
            skipped += 1
            continue

        slug = base
        suffix = 2
        while slug in taken:
            slug = f"{base}-{suffix}"
            suffix += 1
        taken.add(slug)

        session.add(
            Entity(
                campaign_id=context.campaign.id,
                type=item.type,
                name=item.name,
                slug=slug,
                summary=item.summary,
                body=item.body,
                tags=item.tags,
                data=item.data,
                visibility=item.visibility,
            )
        )
        created += 1

    await session.flush()
    return EntityBulkResult(created=created, skipped=skipped)


@router.put("/entities/{entity_id}/fog", response_model=EntityDetail)
async def set_fog(
    entity_id: uuid.UUID,
    payload: FogUpdate,
    context: DmCtx,
    session: SessionDep,
) -> EntityDetail:
    """Uncovering a map is its own write, not a general entity update.

    Painting fog sends the whole mask every time the DM lifts the brush, and
    routing that through the entity PATCH would make each stroke a full write
    of name, summary, body and every type field — so a stroke saved mid-session
    would quietly overwrite whatever someone had just typed on another screen.
    This touches one key and leaves the rest of `data` exactly as it was.

    DM only: the fog is a record of what the party has been shown, so letting a
    player write to it would be handing them the eraser.
    """
    entity = await session.get(Entity, entity_id)

    if entity is None or entity.campaign_id != context.campaign.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # A new dict, because SQLAlchemy tracks JSONB by identity — mutating the
    # existing one in place is a change it never notices and never persists.
    data = dict(entity.data)

    if payload.fog is None:
        data.pop("fog", None)
    else:
        data["fog"] = payload.fog.model_dump()

    entity.data = data
    await session.flush()

    # `updated_at` carries an onupdate default, so the flush leaves it expired
    # and serialising the row would try to fetch it from outside the async
    # context. Refreshing here loads it where awaiting is still allowed.
    await session.refresh(entity)

    return await _detail(session, context, entity)


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the DM can do that")

    # A player edits the sheet, not who gets to see it or whose it is
    if not context.is_dm:
        changes.pop("visibility", None)
        changes.pop("player_id", None)

        # They were never sent the DM's fields, so their `data` can't carry them
        # back — fold the edit in rather than letting it wipe them
        if "data" in changes:
            changes["data"] = entity_service.merge_dm_data(entity.data, changes["data"])

    if changes.get("player_id") is not None:
        await _require_seat(session, context, changes["player_id"])

    rewritten = 0
    old_name = entity.name

    if "name" in changes and changes["name"] != entity.name:
        entity.slug = await entity_service.unique_slug(
            session, context.campaign.id, changes["name"], exclude_id=entity.id
        )

    for field, value in changes.items():
        setattr(entity, field, value)

    if "player_id" in changes:
        await player_service.sync_character_owner(session, entity)

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

    # Containment is the one relation with a direction that has to stay
    # acyclic. Putting a region inside one of its own towns reads as a typo,
    # but what it produces is a breadcrumb that never ends and a tree that
    # can't be drawn — cheaper to refuse here than to defend everywhere after.
    if payload.relation is LinkRelation.LOCATED_IN and await entity_service.would_make_a_loop(
        session, entity.id, target.id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"“{target.name}” is already inside “{entity.name}”",
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
        session.add(EntityLink(from_id=entity.id, to_id=target.id, relation=payload.relation))
        await session.flush()

    return EntityRead.model_validate(entity).model_copy(
        update={"data": entity_service.visible_data(entity.data, context.is_dm)}
    )


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
    return EntityRead.model_validate(entity).model_copy(
        update={"data": entity_service.visible_data(entity.data, context.is_dm)}
    )


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
