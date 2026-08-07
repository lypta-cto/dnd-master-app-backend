"""A campaign that isn't empty on the first evening.

A blank campaign is technically correct and practically useless: the first thing
a DM needs is a goblin to throw and a tavern to throw it in. This is a small,
deliberately generic starter set — original text and plain numbers, not anyone's
published bestiary — that a DM can take, rename and rewrite.

Everything lands as ordinary entities, so nothing here is special-cased later:
the starter goblin and a goblin you write yourself are the same kind of thing.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign
from app.models.entity import Entity, EntityType, Visibility
from app.services import entities as entity_service

MONSTERS: list[dict[str, Any]] = [
    {
        "name": "Goblin",
        "summary": "Small, quick, and braver in numbers than it has any right to be.",
        "data": {"kind": "humanoid", "cr": "1/4", "ac": "15", "hp": "7", "speed": "30 ft.",
                 "abilities": "8/14/10/10/8/8"},
        "body": "Fights dirty and runs early. A pack of six is a real fight for level 1s.",
    },
    {
        "name": "Wolf",
        "summary": "Hunts in a pack and goes for whoever is already down.",
        "data": {"kind": "beast", "cr": "1/4", "ac": "13", "hp": "11", "speed": "40 ft.",
                 "abilities": "12/15/12/3/12/6"},
        "body": "Knocks a target prone on a good hit, then the rest of the pack piles on.",
    },
    {
        "name": "Skeleton",
        "summary": "Bone held together by somebody else's will.",
        "data": {"kind": "undead", "cr": "1/4", "ac": "13", "hp": "13", "speed": "30 ft.",
                 "abilities": "10/14/15/6/8/5"},
        "body": "Ignores fear and pain. Blunt weapons break it faster than blades.",
    },
    {
        "name": "Bandit",
        "summary": "Desperate rather than evil, and willing to talk if losing.",
        "data": {"kind": "humanoid", "cr": "1/8", "ac": "12", "hp": "11", "speed": "30 ft.",
                 "abilities": "11/12/12/10/10/10"},
        "body": "Good for a first fight the party can end with words instead.",
    },
    {
        "name": "Zombie",
        "summary": "Slow, stupid, and hard to put down for good.",
        "data": {"kind": "undead", "cr": "1/4", "ac": "8", "hp": "22", "speed": "20 ft.",
                 "abilities": "13/6/16/3/6/5"},
        "body": "Keeps standing back up on a bad roll — dread rather than danger.",
    },
    {
        "name": "Giant Rat",
        "summary": "Cellar vermin the size of a dog.",
        "data": {"kind": "beast", "cr": "1/8", "ac": "12", "hp": "7", "speed": "30 ft.",
                 "abilities": "7/15/11/2/10/4"},
        "body": "Never a threat alone. Twelve of them in a flooded cellar is another matter.",
    },
    {
        "name": "Dire Wolf",
        "summary": "A wolf grown to the size of a horse, and no less clever for it.",
        "data": {"kind": "beast", "cr": "1", "ac": "14", "hp": "37", "speed": "50 ft.",
                 "abilities": "17/15/15/3/12/7"},
        "body": "The thing that turns a night in the woods into a chase.",
    },
    {
        "name": "Cultist",
        "summary": "An ordinary person who has been promised something.",
        "data": {"kind": "humanoid", "cr": "1/8", "ac": "12", "hp": "9", "speed": "30 ft.",
                 "abilities": "11/12/10/10/11/10"},
        "body": "Most useful alive. Knows one thing the party needs and won't say it easily.",
    },
    {
        "name": "Ghoul",
        "summary": "Hungry, fast, and paralysing to the touch.",
        "data": {"kind": "undead", "cr": "1", "ac": "12", "hp": "22", "speed": "30 ft.",
                 "abilities": "13/15/10/7/10/6"},
        "body": "One paralysed player turns a routine fight tense in a single round.",
    },
    {
        "name": "Ogre",
        "summary": "Enormous, slow-witted, and strong enough to end a character in one swing.",
        "data": {"kind": "giant", "cr": "2", "ac": "11", "hp": "59", "speed": "40 ft.",
                 "abilities": "19/8/16/5/7/7"},
        "body": "A boss for a low-level party. Bargains badly, but it does bargain.",
    },
]

LOCATIONS: list[dict[str, Any]] = [
    {
        "name": "The Tavern",
        "summary": "Where the party meets, hears rumours, and starts most trouble.",
        "data": {"kind": "building"},
        "body": "Rename it and give the innkeeper a name — that's usually enough to make it real.",
    },
    {
        "name": "Market Square",
        "summary": "The town's ears. Nothing happens here privately.",
        "data": {"kind": "building"},
        "body": "Good for rumours, a public scene, or a chase through the stalls.",
    },
    {
        "name": "The Temple",
        "summary": "Healing, questions nobody wants asked, and someone who knows too much.",
        "data": {"kind": "building"},
        "body": "Useful as the safe place — right up until it isn't.",
    },
    {
        "name": "The Road Out",
        "summary": "The way in and the way out, and the last place anyone was seen.",
        "data": {"kind": "wilderness"},
        "body": "Travel scenes belong here. So does the ambush.",
    },
    {
        "name": "The Old Ruin",
        "summary": "Older than the town, and nobody local goes near it after dark.",
        "data": {"kind": "dungeon"},
        "body": "A first dungeon: three rooms, one trap, one thing that should not be awake.",
    },
    {
        "name": "The Woods",
        "summary": "Close enough to walk to, big enough to lose someone in.",
        "data": {"kind": "wilderness"},
        "body": "Where the thing everyone blames is supposed to live.",
    },
]


async def install(session: AsyncSession, campaign: Campaign) -> int:
    """Drop the starter set into a campaign, skipping anything already named.

    Re-running is safe: a DM who already wrote their own Goblin keeps it.
    """
    existing = {
        name.casefold()
        for name in (
            await session.execute(
                select(Entity.name).where(Entity.campaign_id == campaign.id)
            )
        ).scalars()
    }

    created = 0

    for kind, rows, visibility in (
        (EntityType.MONSTER, MONSTERS, Visibility.DM_ONLY),
        (EntityType.LOCATION, LOCATIONS, Visibility.SHARED),
    ):
        for row in rows:
            if row["name"].casefold() in existing:
                continue

            session.add(
                Entity(
                    campaign_id=campaign.id,
                    type=kind,
                    name=row["name"],
                    slug=await entity_service.unique_slug(session, campaign.id, row["name"]),
                    summary=row["summary"],
                    body=row["body"],
                    data=row["data"],
                    visibility=visibility,
                    tags=["starter"],
                )
            )
            created += 1

    await session.flush()
    return created
