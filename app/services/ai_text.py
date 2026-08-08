"""Drafting prose.

The DM stays the author — this writes a first draft they will rewrite. So the
prompts ask for something specific and usable at the table (a place with things
to notice, a person with a want), not a page of atmosphere, and the result lands
in the entity's body where it can be edited like anything they typed themselves.

One provider, reached over plain HTTP rather than a vendor SDK: the request is
four fields and swapping providers should stay a one-file change. Nothing here
is stored — the draft goes back to the client, and saving it is the DM's call.
"""

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

CHAT_URL = "https://api.openai.com/v1/chat/completions"

# gpt-4o-mini, dollars per million tokens. Alongside the model they belong to,
# so changing AI_TEXT_MODEL without these makes the ledger a confident lie.
INPUT_RATE = 0.15
OUTPUT_RATE = 0.60

SYSTEM = """You write for a Dungeon Master preparing a session, and everything \
you write has to be usable at a table tonight.

Write in the DM's own language — match the language of their brief.

Concrete over atmospheric: name what a character notices, who is present and \
what they want, what could go wrong. Prefer specific detail (a smell, a name, \
an object out of place) to adjectives. No purple prose, no rules text, no stat \
blocks, no headings unless asked.

Leave hooks the DM can pull on rather than resolving them, and leave room for \
the players to be the ones who act."""

BRIEFS: dict[str, str] = {
    "location": (
        "Describe this place in 120-180 words: what the party sees and hears "
        "arriving, two or three things worth investigating, and who is around."
    ),
    "npc": (
        "Describe this person in 100-150 words: how they come across, how they "
        "speak, what they want, and what they would rather not discuss."
    ),
    "item": (
        "Describe this item in 80-120 words: what it looks and feels like, what "
        "it does, and one thing about it that is not obvious."
    ),
    "scene": (
        "Describe this scene in 120-180 words: how it opens, what the party can "
        "do here, and what they should leave knowing."
    ),
    "encounter": (
        "Describe this encounter in 100-150 words: what starts it, what the "
        "opposition wants (which is rarely 'kill them'), and how it can end "
        "without a fight."
    ),
    "faction": (
        "Describe this group in 100-150 words: who belongs, what they want, how "
        "they are seen locally, and where they overreach."
    ),
    "monster": (
        "Describe this creature in 80-120 words: how it hunts, what it does on "
        "its first turn, and one detail that makes it memorable."
    ),
    "quest": (
        "Describe this thread in 100-150 words: who asks, what they actually "
        "need, and what makes it harder than it sounds."
    ),
}

DEFAULT_BRIEF = "Write 100-150 words a DM can read at the table and use."


def configured() -> bool:
    return bool(settings.OPENAI_API_KEY)


def describe_facts(facts: dict[str, str] | None) -> str:
    """The type's own fields as a sentence the model will actually use.

    These were being left out entirely, which is how a kobold beggar came back
    described as a cheerful human innkeeper: race and occupation were sitting
    in the form the whole time and never reached the prompt.
    """
    if not facts:
        return ""

    written = [
        f"{key.replace('_', ' ')}: {str(value).strip()}"
        for key, value in facts.items()
        # `dm_` fields are the DM's private notes about the thing, not a
        # description of it — and sending them would put the twist in the prose
        # the players get read.
        if value and not key.startswith("dm_") and key not in {"cover_focus", "pins", "fog"}
    ]

    return ", ".join(written)


def build_prompt(
    kind: str,
    name: str,
    brief: str | None,
    context: str | None,
    facts: dict[str, str] | None = None,
) -> str:
    parts = [BRIEFS.get(kind, DEFAULT_BRIEF), f"\nIt is called: {name}"]

    if (written := describe_facts(facts)):
        parts.append(f"\nWhat is already established about it — keep all of it true: {written}")
    if brief:
        parts.append(f"\nThe DM's notes: {brief}")
    if context:
        # The campaign's own premise and tone, so drafts sound like this game
        parts.append(f"\nThe campaign so far: {context}")

    # Last line on purpose: the language rule is the one the model most often
    # drops, and a DM writing in Serbian does not want an English draft back.
    # Judge by the notes — the campaign context may be in a different language.
    parts.append(
        "\nWrite your answer in the same language as the DM's notes above."
        if brief
        else "\nWrite your answer in the same language as the name above."
    )

    return "\n".join(parts)


@dataclass(frozen=True)
class Drafted:
    """The paragraph, and what it cost — every generation goes in the ledger."""

    text: str
    cents: float


async def draft(
    kind: str,
    name: str,
    brief: str | None,
    context: str | None,
    facts: dict[str, str] | None = None,
) -> Drafted:
    """One short draft. A paragraph, not a plan — a small model is the right size."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Drafting is off — set OPENAI_API_KEY to turn it on.",
        )

    prompt = build_prompt(kind, name, brief, context, facts)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                CHAT_URL,
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": settings.AI_TEXT_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 700,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't reach the writing model.",
        ) from exc

    if response.status_code >= 400:
        # The provider's own message usually says exactly what it disliked
        detail = response.json().get("error", {}).get("message", "Drafting failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    body = response.json()
    choices = body.get("choices") or []
    text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""

    if not text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model returned nothing usable.",
        )

    # The provider's own count, so the ledger records what was charged rather
    # than what we guessed would be
    usage = body.get("usage") or {}
    cents = (
        usage.get("prompt_tokens", 0) * INPUT_RATE + usage.get("completion_tokens", 0) * OUTPUT_RATE
    ) / 10_000

    return Drafted(text=text, cents=round(cents, 4))
