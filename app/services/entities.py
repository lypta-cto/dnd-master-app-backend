import re
import unicodedata
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityLink, LinkRelation, Visibility

# [[Name]] or [[Name|what to show]] — the second form lets prose read naturally
# while still pointing at the canonical entity.
WIKI_LINK = re.compile(r"\[\[([^\[\]|]{1,200}?)(?:\|[^\[\]]{0,200}?)?\]\]")


def slugify(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return cleaned or "untitled"


async def unique_slug(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """Slugs are unique per campaign, so two campaigns can both have a Goblin King."""
    base = slugify(name)
    candidate = base
    suffix = 2

    while True:
        query = select(Entity.id).where(Entity.campaign_id == campaign_id, Entity.slug == candidate)
        if exclude_id is not None:
            query = query.where(Entity.id != exclude_id)

        if (await session.execute(query.limit(1))).scalar_one_or_none() is None:
            return candidate

        candidate = f"{base}-{suffix}"
        suffix += 1


def extract_wiki_links(body: str | None) -> list[str]:
    """Returns the referenced names, de-duplicated, in order of appearance."""
    if not body:
        return []

    seen: dict[str, None] = {}
    for match in WIKI_LINK.finditer(body):
        name = match.group(1).strip()
        if name:
            seen.setdefault(name.casefold(), None)
            seen[name.casefold()] = name  # type: ignore[assignment]

    return list(seen.values())  # type: ignore[arg-type]


async def sync_wiki_links(session: AsyncSession, entity: Entity) -> tuple[int, list[str]]:
    """
    Rewrites this entity's `mentions` links from its body.

    Returns (linked, unresolved). Unresolved names are handed back so the UI can
    offer "create it" rather than silently dropping the reference.

    Only `mentions` rows are touched — hand-made typed relations survive an edit.
    """
    names = extract_wiki_links(entity.body)

    await session.execute(
        delete(EntityLink).where(
            EntityLink.from_id == entity.id,
            EntityLink.relation == LinkRelation.MENTIONS,
        )
    )

    if not names:
        return 0, []

    # Case-insensitive match on name or slug, so [[blackmoor keep]] finds it
    lowered = [name.casefold() for name in names]
    result = await session.execute(
        select(Entity).where(
            Entity.campaign_id == entity.campaign_id,
            or_(func.lower(Entity.name).in_(lowered), Entity.slug.in_(lowered)),
        )
    )

    by_key: dict[str, Entity] = {}
    for candidate in result.scalars():
        by_key[candidate.name.casefold()] = candidate
        by_key.setdefault(candidate.slug, candidate)

    unresolved: list[str] = []
    linked = 0

    for name in names:
        target = by_key.get(name.casefold())

        if target is None:
            unresolved.append(name)
            continue
        if target.id == entity.id:
            continue  # self-references aren't links

        session.add(EntityLink(from_id=entity.id, to_id=target.id, relation=LinkRelation.MENTIONS))
        linked += 1

    await session.flush()
    return linked, unresolved


async def rewrite_references(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    old_name: str,
    new_name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> int:
    """
    Renaming an entity would orphan every [[Old Name]] written in prose, so the
    prose follows the rename. Returns how many entities were rewritten —
    surfaced in the UI, because silent edits to your own writing feel wrong.

    Only the [[target]] part is touched; [[Old|display text]] keeps its label.
    """
    if old_name.strip().casefold() == new_name.strip().casefold():
        return 0

    # Candidate set via ILIKE, precise match via regex — ILIKE alone would also
    # hit plain prose mentioning the name outside brackets.
    result = await session.execute(
        select(Entity).where(
            Entity.campaign_id == campaign_id,
            Entity.body.ilike(f"%{old_name}%"),
        )
    )

    pattern = re.compile(
        r"\[\[\s*" + re.escape(old_name.strip()) + r"\s*(\||\]\])",
        re.IGNORECASE,
    )

    rewritten = 0
    for entity in result.scalars():
        if exclude_id is not None and entity.id == exclude_id:
            continue

        new_body, count = pattern.subn(f"[[{new_name.strip()}\\1", entity.body or "")
        if count:
            entity.body = new_body
            rewritten += 1

    await session.flush()
    return rewritten


async def resync_bodies_referencing(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> int:
    """
    Re-resolves links for every entity whose prose mentions [[name]].

    Needed after a rename in *both* directions: bodies rewritten to the new
    name must link to it, and bodies that already referenced the new name —
    written back when it was unresolved — finally get their link too.
    """
    result = await session.execute(
        select(Entity).where(
            Entity.campaign_id == campaign_id,
            Entity.body.ilike(f"%[[%{name}%]]%"),
        )
    )

    resynced = 0
    for entity in result.scalars():
        if exclude_id is not None and entity.id == exclude_id:
            continue
        await sync_wiki_links(session, entity)
        resynced += 1

    return resynced


def visibility_filter(is_dm: bool, user_id: uuid.UUID | None = None):
    """DMs see everything; players see what's shared — plus what they own,
    whatever its visibility, because your own character sheet is never a secret
    from you."""
    if is_dm:
        return None

    shared = Entity.visibility.in_([Visibility.SHARED, Visibility.PUBLIC])
    if user_id is None:
        return shared
    return or_(shared, Entity.owner_id == user_id)


async def search(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    query: str,
    *,
    is_dm: bool,
    user_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[tuple[Entity, float]]:
    """
    Full-text over the whole campaign in one query — the payoff for putting
    everything on one spine instead of a table per type.
    """
    tsquery = func.websearch_to_tsquery("simple", query)
    rank = func.ts_rank(Entity.search_vector, tsquery)

    statement = (
        select(Entity, rank.label("rank"))
        .where(Entity.campaign_id == campaign_id, Entity.search_vector.op("@@")(tsquery))
        .order_by(rank.desc(), Entity.name)
        .limit(limit)
    )

    if (visible := visibility_filter(is_dm, user_id)) is not None:
        statement = statement.where(visible)

    result = await session.execute(statement)
    return [(row[0], float(row[1])) for row in result.all()]


async def backlinks(
    session: AsyncSession,
    entity_id: uuid.UUID,
    *,
    is_dm: bool,
    user_id: uuid.UUID | None = None,
) -> list[tuple[Entity, LinkRelation]]:
    """Everything pointing *at* this entity — the "mentioned in" panel."""
    statement = (
        select(Entity, EntityLink.relation)
        .join(EntityLink, EntityLink.from_id == Entity.id)
        .where(EntityLink.to_id == entity_id)
        .order_by(Entity.name)
    )

    if (visible := visibility_filter(is_dm, user_id)) is not None:
        statement = statement.where(visible)

    return [(row[0], row[1]) for row in (await session.execute(statement)).all()]


async def outgoing_links(
    session: AsyncSession,
    entity_id: uuid.UUID,
    *,
    is_dm: bool,
    user_id: uuid.UUID | None = None,
) -> list[tuple[Entity, LinkRelation]]:
    statement = (
        select(Entity, EntityLink.relation)
        .join(EntityLink, EntityLink.to_id == Entity.id)
        .where(EntityLink.from_id == entity_id)
        .order_by(Entity.name)
    )

    if (visible := visibility_filter(is_dm, user_id)) is not None:
        statement = statement.where(visible)

    return [(row[0], row[1]) for row in (await session.execute(statement)).all()]
