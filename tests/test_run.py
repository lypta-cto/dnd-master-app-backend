"""The evening in progress — the DM's screen behind the screen."""

from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, make_entity, sign_up

PREFIX = settings.API_V1_PREFIX


async def test_a_fresh_campaign_has_an_empty_evening(client: AsyncClient):
    dm = await sign_up(client, "run-fresh@example.com")
    cid = (await make_campaign(client, dm))["id"]

    state = (await client.get(f"{PREFIX}/campaigns/{cid}/run", headers=dm)).json()
    assert state["active"] is False
    assert state["scene_id"] is None
    assert state["revealed"] == []
    assert state["spotlight"] == {}


async def test_running_an_evening_keeps_scene_clues_and_spotlight(client: AsyncClient):
    dm = await sign_up(client, "run-play@example.com")
    cid = (await make_campaign(client, dm))["id"]

    scene = await make_entity(client, dm, cid, type="scene", name="Arrival")
    clue = await make_entity(client, dm, cid, type="clue", name="Bloody pendant")
    player = (
        await client.post(f"{PREFIX}/campaigns/{cid}/players", json={"name": "Ana"}, headers=dm)
    ).json()

    saved = await client.put(
        f"{PREFIX}/campaigns/{cid}/run",
        json={
            "active": True,
            "scene_id": scene["id"],
            "revealed": [clue["id"]],
            "spotlight": {player["id"]: 2},
            "clock": [{"label": "22:00", "text": "Another villager disappears.", "done": False}],
            "notes": "Ana asked about the church — pay that off.",
        },
        headers=dm,
    )
    assert saved.status_code == 200, saved.text

    state = (await client.get(f"{PREFIX}/campaigns/{cid}/run", headers=dm)).json()
    assert state["scene_id"] == scene["id"]
    assert state["revealed"] == [clue["id"]]
    assert state["spotlight"] == {player["id"]: 2}
    assert state["clock"][0]["text"].startswith("Another villager")


async def test_a_deleted_scene_leaves_the_evening_standing(client: AsyncClient):
    """Mid-session is the worst possible time for a cascade."""
    dm = await sign_up(client, "run-delete@example.com")
    cid = (await make_campaign(client, dm))["id"]
    scene = await make_entity(client, dm, cid, type="scene", name="Doomed")

    await client.put(
        f"{PREFIX}/campaigns/{cid}/run",
        json={"active": True, "scene_id": scene["id"]},
        headers=dm,
    )
    await client.delete(f"{PREFIX}/campaigns/{cid}/entities/{scene['id']}", headers=dm)

    state = (await client.get(f"{PREFIX}/campaigns/{cid}/run", headers=dm)).json()
    assert state["active"] is True
    assert state["scene_id"] == scene["id"]


async def test_the_run_screen_is_the_dms_alone(client: AsyncClient):
    dm = await sign_up(client, "run-dm@example.com")
    guest = await sign_up(client, "run-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "run-player@example.com", "role": "player"},
        headers=dm,
    )

    assert (await client.get(f"{PREFIX}/campaigns/{cid}/run", headers=guest)).status_code == 403
    assert (
        await client.put(f"{PREFIX}/campaigns/{cid}/run", json={"active": True}, headers=guest)
    ).status_code == 403
