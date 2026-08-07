"""Drafting is off until a key exists, and never writes without the DM's say-so."""

from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, make_entity, sign_up

PREFIX = settings.API_V1_PREFIX


async def test_status_reports_what_is_switched_on(client: AsyncClient):
    dm = await sign_up(client, "ai-status@example.com")
    cid = (await make_campaign(client, dm))["id"]

    status_body = (await client.get(f"{PREFIX}/campaigns/{cid}/ai", headers=dm)).json()
    assert set(status_body) == {"text", "images"}
    assert status_body["text"] is bool(settings.OPENAI_API_KEY)
    assert status_body["images"] is bool(settings.OPENAI_API_KEY)


async def test_without_a_key_the_api_says_so_rather_than_failing_oddly(client: AsyncClient):
    dm = await sign_up(client, "ai-nokey@example.com")
    cid = (await make_campaign(client, dm))["id"]

    if settings.OPENAI_API_KEY:
        return  # a configured environment has nothing to assert here

    refused = await client.post(
        f"{PREFIX}/campaigns/{cid}/ai/draft",
        json={"type": "location", "name": "The Old Mill"},
        headers=dm,
    )
    assert refused.status_code == 503
    assert "OPENAI_API_KEY" in refused.json()["detail"]


async def test_illustrating_needs_something_written_first(client: AsyncClient):
    """The picture is drawn from the page, so an empty page is a bad request."""
    dm = await sign_up(client, "ai-empty@example.com")
    cid = (await make_campaign(client, dm))["id"]
    entity = await make_entity(client, dm, cid, type="location", name="Nowhere", summary=None)

    refused = await client.post(
        f"{PREFIX}/campaigns/{cid}/ai/entities/{entity['id']}/illustrate",
        json={},
        headers=dm,
    )
    assert refused.status_code == 400


async def test_drafting_is_dm_only(client: AsyncClient):
    dm = await sign_up(client, "ai-dm@example.com")
    guest = await sign_up(client, "ai-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "ai-player@example.com", "role": "player"},
        headers=dm,
    )

    refused = await client.post(
        f"{PREFIX}/campaigns/{cid}/ai/draft",
        json={"type": "npc", "name": "Someone"},
        headers=guest,
    )
    assert refused.status_code == 403


async def test_the_brief_carries_the_campaign_and_the_dms_notes(client: AsyncClient):
    """Prompt building is pure — worth testing without spending a token."""
    from app.services import ai_text

    prompt = ai_text.build_prompt(
        kind="location",
        name="Stara vodenica",
        brief="Napuštena, tragovi krvi vode u podrum.",
        context="Gothic horror in an isolated valley. Tone: dark.",
    )

    assert "Stara vodenica" in prompt
    assert "tragovi krvi" in prompt
    assert "Tone: dark" in prompt
    assert "120-180 words" in prompt  # the location brief, not the fallback


async def test_image_prompts_lead_with_what_the_dm_wrote(client: AsyncClient):
    from app.services import ai_image

    prompt = ai_image.build_prompt(
        kind="npc",
        name="Otac Aldrik",
        description="Seoski sveštenik, jedini koji izlazi noću.",
        extra="at night, lantern light",
    )

    assert prompt.startswith("Otac Aldrik. Seoski sveštenik")
    assert "at night, lantern light" in prompt
    assert "character portrait" in prompt
    assert "No text" in prompt
    # The old wording ("dramatic lighting, muted palette") produced soft, murky
    # pictures at every price point. Asking for focus is what fixed them.
    assert "crisp focus" in prompt
    assert "muted palette" not in prompt


async def test_the_cheap_tier_is_the_default(client: AsyncClient):
    """A click should cost a cent unless the DM chooses otherwise."""
    from app.schemas.ai import IllustrateRequest
    from app.services.ai_image import QUALITIES

    assert IllustrateRequest().quality == "draft"
    assert QUALITIES["draft"] == "low"
    assert QUALITIES["good"] == "medium"
