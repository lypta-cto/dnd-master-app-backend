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


# --- The purse ----------------------------------------------------------------


async def test_a_dollar_is_ten_thousand_coins(client: AsyncClient):
    """The rate exists so the cheapest thing the app does still costs >1 coin.

    At the obvious first guess — a hundred coins to the dollar — a text draft
    comes to 0.024 of one and every line of the ledger reads as zero.
    """
    from app.services import coins

    assert coins.COINS_PER_DOLLAR == 10_000
    assert coins.coins(coins.micros_from_cents(0.024)) == 2.4   # a text draft
    assert coins.coins(coins.micros_from_cents(0.24)) == 24.0   # a draft image
    assert coins.coins(coins.micros_from_cents(0.87)) == 87.0   # a good one


async def test_the_purse_starts_empty_and_counts_what_is_added(client: AsyncClient):
    dm = await sign_up(client, "purse-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]

    empty = (await client.get(f"{PREFIX}/campaigns/{cid}/ai/purse", headers=dm)).json()
    assert empty["balance"] == 0
    assert empty["entries"] == []

    topped = await client.post(
        f"{PREFIX}/campaigns/{cid}/ai/purse/topup", json={"usd": 10}, headers=dm
    )
    assert topped.status_code == 201

    body = topped.json()
    assert body["balance"] == 100_000  # ten dollars
    assert body["added"] == 100_000
    assert body["entries"][0]["detail"] == "Added $10.00"


async def test_a_slipped_decimal_point_cannot_record_a_fortune(client: AsyncClient):
    dm = await sign_up(client, "purse-bounds@example.com")
    cid = (await make_campaign(client, dm))["id"]

    for bad in [0, -5, 100_000]:
        response = await client.post(
            f"{PREFIX}/campaigns/{cid}/ai/purse/topup", json={"usd": bad}, headers=dm
        )
        assert response.status_code == 422, f"{bad} was accepted"


async def test_the_purse_is_the_dms_and_scoped_to_one_campaign(client: AsyncClient):
    dm = await sign_up(client, "purse-owner@example.com")
    player = await sign_up(client, "purse-player@example.com")
    cid = (await make_campaign(client, dm))["id"]
    other = (await make_campaign(client, dm, name="Second table"))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "purse-player@example.com", "role": "player"},
        headers=dm,
    )
    await client.post(f"{PREFIX}/campaigns/{cid}/ai/purse/topup", json={"usd": 5}, headers=dm)

    # What one campaign spends is not the other's business
    elsewhere = (await client.get(f"{PREFIX}/campaigns/{other}/ai/purse", headers=dm)).json()
    assert elsewhere["balance"] == 0

    # Spending is the DM's, and so is the record of it
    refused = await client.get(f"{PREFIX}/campaigns/{cid}/ai/purse", headers=player)
    assert refused.status_code == 403


async def test_the_prompt_carries_what_the_dm_already_filled_in(client: AsyncClient):
    """A kobold beggar was coming back as a cheerful human innkeeper: race and
    occupation sat in the form and never reached the model."""
    from app.services import ai_text

    prompt = ai_text.build_prompt(
        kind="npc",
        name="Vlerija",
        brief="Krčmarica.",
        context=None,
        facts={"race": "Kobold", "occupation": "Beggar", "status": "alive"},
    )

    assert "Kobold" in prompt
    assert "Beggar" in prompt


async def test_the_dms_private_notes_never_reach_the_model(client: AsyncClient):
    """`dm_` fields are the twist. Drafting from them would write it into the
    prose the players get read."""
    from app.services import ai_text

    written = ai_text.describe_facts(
        {
            "race": "Kobold",
            "dm_players_think": "She is harmless",
            "dm_notes": "She poisons the ale",
        }
    )

    assert "Kobold" in written
    assert "poisons" not in written
    assert "harmless" not in written


async def test_a_map_prompt_is_cartography_not_a_scene(client: AsyncClient):
    """Depth-of-field on a village map blurs half the village — maps get an
    evenly-lit cartographic finish, and never any lettering."""
    from app.services import ai_image

    prompt = ai_image.build_prompt(
        kind="map",
        name="Selo Podgorje",
        description="Selo na obali reke, sa mlinom i starim hrastom.",
        extra=None,
    )

    assert "cartography" in prompt
    assert "No grid lines" in prompt
    assert "no lettering" in prompt
    # The frame leads and the story follows — description-first drew the
    # goblin selling soap instead of the village he sells it in
    assert prompt.startswith("A hand-drawn fantasy map viewed directly from above")
    assert "no people, no creatures, no figures" in prompt
    # The painterly-scene half must not leak in
    assert "silhouette" not in prompt
