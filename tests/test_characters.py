from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, make_entity, sign_up

PREFIX = settings.API_V1_PREFIX


async def add_player(client, dm_headers, cid, email):
    await sign_up(client, email)
    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": email, "role": "player"},
        headers=dm_headers,
    )
    token = (
        await client.post(
            f"{PREFIX}/auth/login", json={"email": email, "password": "supersecret1"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- A5: rename rewrites references ------------------------------------------


async def test_rename_rewrites_references_in_prose(client: AsyncClient):
    dm = await sign_up(client, "ren1@example.com")
    cid = (await make_campaign(client, dm))["id"]

    keep = await make_entity(client, dm, cid, type="location", name="Blackmoor Keep")
    scout = await make_entity(
        client, dm, cid, name="Scout",
        body="Saw lights at [[Blackmoor Keep]] and [[blackmoor keep|the old fort]].",
    )

    renamed = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{keep['id']}",
        json={"name": "Ravenmoor Keep"},
        headers=dm,
    )
    assert renamed.status_code == 200
    assert renamed.json()["rewritten_references"] == 1  # one entity touched

    detail = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{scout['id']}", headers=dm
    )
    body = detail.json()["body"]
    assert "[[Ravenmoor Keep]]" in body
    assert "[[Ravenmoor Keep|the old fort]]" in body  # label survived
    assert detail.json()["unresolved_links"] == []
    assert [link["name"] for link in detail.json()["links"]] == ["Ravenmoor Keep"]


async def test_rename_leaves_plain_prose_alone(client: AsyncClient):
    dm = await sign_up(client, "ren2@example.com")
    cid = (await make_campaign(client, dm))["id"]

    keep = await make_entity(client, dm, cid, type="location", name="Vallaki")
    note = await make_entity(
        client, dm, cid, type="note", name="Recap",
        body="We talked about Vallaki without linking it. But [[Vallaki]] is linked.",
    )

    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{keep['id']}",
        json={"name": "New Vallaki"},
        headers=dm,
    )

    body = (
        await client.get(f"{PREFIX}/campaigns/{cid}/entities/{note['id']}", headers=dm)
    ).json()["body"]
    # Plain mention untouched; only the wiki link moved
    assert "talked about Vallaki without" in body
    assert "[[New Vallaki]]" in body


# --- B1: characters and ownership --------------------------------------------


async def test_player_creates_their_own_character(client: AsyncClient):
    dm = await sign_up(client, "chr1@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "chrplayer1@example.com")

    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={"type": "character", "name": "Ezra the Bold", "visibility": "dm_only"},
        headers=player,
    )

    assert response.status_code == 201
    body = response.json()
    # Ownership forced to self, visibility forced to shared
    assert body["visibility"] == "shared"
    assert body["owner_id"] is not None


async def test_player_cannot_create_other_types(client: AsyncClient):
    dm = await sign_up(client, "chr2@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "chrplayer2@example.com")

    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={"type": "npc", "name": "Sneaky"},
        headers=player,
    )
    assert response.status_code == 403


async def test_player_edits_own_sheet_but_not_visibility(client: AsyncClient):
    dm = await sign_up(client, "chr3@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "chrplayer3@example.com")

    sheet = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": "character", "name": "Ireena"},
            headers=player,
        )
    ).json()

    updated = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{sheet['id']}",
        json={"data": {"current_hp": 17, "max_hp": 24}, "visibility": "dm_only"},
        headers=player,
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["current_hp"] == 17
    # The visibility change was silently dropped, not applied
    assert updated.json()["visibility"] == "shared"


async def test_player_cannot_edit_someone_elses_character(client: AsyncClient):
    dm = await sign_up(client, "chr4@example.com")
    cid = (await make_campaign(client, dm))["id"]
    owner = await add_player(client, dm, cid, "chrowner@example.com")
    rival = await add_player(client, dm, cid, "chrrival@example.com")

    sheet = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": "character", "name": "Kasimir"},
            headers=owner,
        )
    ).json()

    response = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{sheet['id']}",
        json={"data": {"current_hp": 0}},
        headers=rival,
    )
    assert response.status_code == 403


async def test_owner_sees_their_dm_only_character(client: AsyncClient):
    """The DM may hide a sheet from the party, never from its own player."""
    dm = await sign_up(client, "chr5@example.com")
    cid = (await make_campaign(client, dm))["id"]
    player = await add_player(client, dm, cid, "chrplayer5@example.com")

    sheet = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": "character", "name": "Secret Twin"},
            headers=player,
        )
    ).json()

    # DM tightens visibility
    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{sheet['id']}",
        json={"visibility": "dm_only"},
        headers=dm,
    )

    # Owner still reads it, still finds it in the list
    direct = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{sheet['id']}", headers=player
    )
    assert direct.status_code == 200

    listed = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities?type=character", headers=player
    )
    assert [e["name"] for e in listed.json()["items"]] == ["Secret Twin"]

    # A different player does not
    rival = await add_player(client, dm, cid, "chrrival5@example.com")
    hidden = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{sheet['id']}", headers=rival
    )
    assert hidden.status_code == 404


async def test_renaming_to_an_already_referenced_name_reconnects_prose(client: AsyncClient):
    """Prose written before the entity existed under that name links up the
    moment the rename lands — no manual re-save of every note."""
    dm = await sign_up(client, "ren3@example.com")
    cid = (await make_campaign(client, dm))["id"]

    note = await make_entity(
        client, dm, cid, type="note", name="Prophecy",
        body="It sleeps beneath [[The Amber Temple]].",
    )
    assert note["unresolved_links"] == ["The Amber Temple"]

    shrine = await make_entity(client, dm, cid, type="location", name="Old Shrine")
    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{shrine['id']}",
        json={"name": "The Amber Temple"},
        headers=dm,
    )

    detail = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{note['id']}", headers=dm
    )
    assert [link["name"] for link in detail.json()["links"]] == ["The Amber Temple"]
    assert detail.json()["unresolved_links"] == []
