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
    assert state.json() == {
        "active": False,
        "round": 1,
        "turn_index": 0,
        "combatants": [],
        # No map until the DM picks one — a fight doesn't need a battle map
        "map_id": None,
    }


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


async def test_the_battle_map_survives_a_whole_state_replace(client: AsyncClient):
    """Every field is assigned on PUT. One that quietly wasn't would be worse
    than not having it: the DM picks a map and watches it come back empty."""
    from tests.test_campaign import make_campaign, make_entity, sign_up

    dm = await sign_up(client, "battlemap@example.com")
    cid = (await make_campaign(client, dm))["id"]
    battle_map = await make_entity(client, dm, cid, type="map", name="Pećina")

    saved = await client.put(
        f"{PREFIX}/campaigns/{cid}/combat",
        json={
            "active": True,
            "round": 1,
            "turn_index": 0,
            "map_id": battle_map["id"],
            "combatants": [
                # Placed, and one still waiting to go on the board
                {"id": "a", "name": "Varvarin", "kind": "character", "x": 30.5, "y": 60},
                {"id": "b", "name": "Ogre", "kind": "monster"},
            ],
        },
        headers=dm,
    )
    assert saved.status_code == 200

    body = saved.json()
    assert body["map_id"] == battle_map["id"]
    assert body["combatants"][0]["x"] == 30.5
    # Absent means "not placed", not the top-left corner
    assert body["combatants"][1]["x"] is None

    # And it's still there on the next read
    again = await client.get(f"{PREFIX}/campaigns/{cid}/combat", headers=dm)
    assert again.json()["map_id"] == battle_map["id"]


async def test_a_token_cannot_be_placed_off_the_map(client: AsyncClient):
    from tests.test_campaign import make_campaign, sign_up

    dm = await sign_up(client, "battlemap-bounds@example.com")
    cid = (await make_campaign(client, dm))["id"]

    refused = await client.put(
        f"{PREFIX}/campaigns/{cid}/combat",
        json={
            "active": True,
            "round": 1,
            "turn_index": 0,
            "combatants": [{"id": "a", "name": "Ogre", "kind": "monster", "x": 140, "y": -3}],
        },
        headers=dm,
    )
    assert refused.status_code == 422
