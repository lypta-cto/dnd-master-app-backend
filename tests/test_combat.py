from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, sign_up
from tests.test_characters import add_player

PREFIX = settings.API_V1_PREFIX


async def test_combat_starts_empty_and_inactive(client: AsyncClient):
    dm = await sign_up(client, "cmb1@example.com")
    cid = (await make_campaign(client, dm))["id"]

    state = await client.get(f"{PREFIX}/campaigns/{cid}/combat", headers=dm)

    assert state.status_code == 200
    assert state.json() == {"active": False, "round": 1, "turn_index": 0, "combatants": []}


async def test_dm_runs_a_fight(client: AsyncClient):
    dm = await sign_up(client, "cmb2@example.com")
    cid = (await make_campaign(client, dm))["id"]

    put = await client.put(
        f"{PREFIX}/campaigns/{cid}/combat",
        json={
            "active": True,
            "round": 2,
            "turn_index": 1,
            "combatants": [
                {"id": "a", "name": "Ezmerelda", "kind": "character", "initiative": 18,
                 "max_hp": 24, "current_hp": 17},
                {"id": "b", "name": "Strahd Zombie", "kind": "monster", "initiative": 12,
                 "max_hp": 30, "current_hp": 30, "conditions": ["prone"]},
            ],
        },
        headers=dm,
    )

    assert put.status_code == 200
    body = put.json()
    assert body["round"] == 2
    assert body["combatants"][1]["conditions"] == ["prone"]

    # Survives a fresh read
    again = await client.get(f"{PREFIX}/campaigns/{cid}/combat", headers=dm)
    assert again.json() == body


async def test_turn_index_must_point_at_a_combatant(client: AsyncClient):
    dm = await sign_up(client, "cmb3@example.com")
    cid = (await make_campaign(client, dm))["id"]

    bad = await client.put(
        f"{PREFIX}/campaigns/{cid}/combat",
        json={
            "active": True,
            "turn_index": 5,
            "combatants": [{"id": "a", "name": "Solo", "initiative": 10}],
        },
        headers=dm,
    )
    assert bad.status_code == 422


async def test_players_cannot_see_or_touch_combat(client: AsyncClient):
    dm = await sign_up(client, "cmb4@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "cmbplayer@example.com")

    assert (
        await client.get(f"{PREFIX}/campaigns/{cid}/combat", headers=player)
    ).status_code == 403
    assert (
        await client.put(
            f"{PREFIX}/campaigns/{cid}/combat",
            json={"active": True, "combatants": []},
            headers=player,
        )
    ).status_code == 403
