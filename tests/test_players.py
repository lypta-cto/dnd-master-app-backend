"""Seats at the table — the part that has to work without anyone registering."""

from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, sign_up

PREFIX = settings.API_V1_PREFIX


async def add_player(client, headers, cid, name, **overrides):
    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/players",
        json={"name": name, **overrides},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_table_of_players_needs_no_accounts(client: AsyncClient):
    """The whole point: eight people written down in a couple of minutes."""
    dm = await sign_up(client, "seats-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]

    for name in ("Ana", "Bojan", "Vera"):
        player = await add_player(
            client, dm, cid, name, contact="discord: " + name.lower(), experience="new"
        )
        assert player["account"] is None

    roster = await client.get(f"{PREFIX}/campaigns/{cid}/players", headers=dm)
    assert [p["name"] for p in roster.json()] == ["Ana", "Bojan", "Vera"]


async def test_dm_makes_a_sheet_for_a_player_without_an_account(client: AsyncClient):
    dm = await sign_up(client, "sheet-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "Ana", preferences=["roleplay", "puzzles"])

    created = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={"type": "character", "name": "Arannis", "player_id": player["id"]},
        headers=dm,
    )
    assert created.status_code == 201, created.text

    body = created.json()
    assert body["player_id"] == player["id"]
    # Nobody can log in as Ana, so nobody owns the sheet — the DM keeps it
    assert body["owner_id"] is None

    roster = await client.get(f"{PREFIX}/campaigns/{cid}/players", headers=dm)
    seat = next(p for p in roster.json() if p["id"] == player["id"])
    assert [c["name"] for c in seat["characters"]] == ["Arannis"]


async def test_inviting_an_existing_account_hands_over_the_sheet(client: AsyncClient):
    dm = await sign_up(client, "invite-dm@example.com")
    guest = await sign_up(client, "guest@example.com")
    cid = (await make_campaign(client, dm))["id"]

    player = await add_player(client, dm, cid, "Ana")
    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={
                "type": "character",
                "name": "Arannis",
                "player_id": player["id"],
                "visibility": "shared",
            },
            headers=dm,
        )
    ).json()

    invited = await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{player['id']}/invite",
        json={"email": "guest@example.com"},
        headers=dm,
    )
    assert invited.status_code == 200, invited.text
    assert invited.json()["account"]["email"] == "guest@example.com"

    # The sheet the DM filled in is now theirs to edit
    edited = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"data": {"current_hp": 12}},
        headers=guest,
    )
    assert edited.status_code == 200, edited.text


async def test_registering_later_claims_the_seat(client: AsyncClient):
    """The DM invites an address, the person signs up whenever they get around
    to it, and the seat is waiting."""
    dm = await sign_up(client, "later-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]

    player = await add_player(client, dm, cid, "Vera")
    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={
                "type": "character",
                "name": "Mira",
                "player_id": player["id"],
                "visibility": "shared",
            },
            headers=dm,
        )
    ).json()

    pending = await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{player['id']}/invite",
        json={"email": "vera@example.com"},
        headers=dm,
    )
    assert pending.json()["account"] is None
    assert pending.json()["invited_email"] == "vera@example.com"

    vera = await sign_up(client, "vera@example.com")

    roster = await client.get(f"{PREFIX}/campaigns/{cid}/players", headers=dm)
    seat = next(p for p in roster.json() if p["id"] == player["id"])
    assert seat["account"]["email"] == "vera@example.com"
    assert seat["invited_email"] is None

    mine = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"data": {"current_hp": 5}},
        headers=vera,
    )
    assert mine.status_code == 200, mine.text


async def test_moving_a_sheet_between_seats_moves_who_may_edit_it(client: AsyncClient):
    dm = await sign_up(client, "move-dm@example.com")
    first = await sign_up(client, "first@example.com")
    cid = (await make_campaign(client, dm))["id"]

    seat_one = await add_player(client, dm, cid, "Ana")
    seat_two = await add_player(client, dm, cid, "Bojan")

    await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{seat_one['id']}/invite",
        json={"email": "first@example.com"},
        headers=dm,
    )

    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={
                "type": "character",
                "name": "Arannis",
                "player_id": seat_one["id"],
                "visibility": "shared",
            },
            headers=dm,
        )
    ).json()

    assert (
        await client.patch(
            f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
            json={"data": {"current_hp": 9}},
            headers=first,
        )
    ).status_code == 200

    handed_over = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"player_id": seat_two["id"]},
        headers=dm,
    )
    assert handed_over.status_code == 200, handed_over.text
    assert handed_over.json()["owner_id"] is None

    # Bojan has no account, so nobody but the DM writes this sheet now
    refused = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"data": {"current_hp": 1}},
        headers=first,
    )
    assert refused.status_code == 403


async def test_removing_a_player_keeps_their_character(client: AsyncClient):
    dm = await sign_up(client, "drop-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "Ana")

    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": "character", "name": "Arannis", "player_id": player["id"]},
            headers=dm,
        )
    ).json()

    removed = await client.delete(
        f"{PREFIX}/campaigns/{cid}/players/{player['id']}", headers=dm
    )
    assert removed.status_code == 200

    still_there = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}", headers=dm
    )
    assert still_there.status_code == 200
    assert still_there.json()["player_id"] is None


async def test_players_may_read_the_roster_but_not_write_it(client: AsyncClient):
    dm = await sign_up(client, "roster-dm@example.com")
    guest = await sign_up(client, "roster-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    seat = await add_player(client, dm, cid, "Ana")
    await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{seat['id']}/invite",
        json={"email": "roster-player@example.com"},
        headers=dm,
    )

    assert (await client.get(f"{PREFIX}/campaigns/{cid}/players", headers=guest)).status_code == 200

    refused = await client.post(
        f"{PREFIX}/campaigns/{cid}/players", json={"name": "Sneaky"}, headers=guest
    )
    assert refused.status_code == 403

    # …but they may fix their own row
    mine = await client.patch(
        f"{PREFIX}/campaigns/{cid}/players/{seat['id']}",
        json={"contact": "discord: ana#1234"},
        headers=guest,
    )
    assert mine.status_code == 200


async def test_a_player_creating_their_own_sheet_lands_in_their_seat(client: AsyncClient):
    dm = await sign_up(client, "own-dm@example.com")
    guest = await sign_up(client, "own-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    seat = await add_player(client, dm, cid, "Ana")
    await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{seat['id']}/invite",
        json={"email": "own-player@example.com"},
        headers=dm,
    )

    created = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={"type": "character", "name": "Their Own"},
        headers=guest,
    )
    assert created.status_code == 201
    assert created.json()["player_id"] == seat["id"]
