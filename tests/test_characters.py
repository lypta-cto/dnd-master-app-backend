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


async def test_dm_fields_on_an_entity_never_reach_a_player(client: AsyncClient):
    """`dm_` keys are the notes behind the thing — same rule as the campaign."""
    dm = await sign_up(client, "dmfields-dm@example.com")
    player = await sign_up(client, "dmfields-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "dmfields-player@example.com", "role": "player"},
        headers=dm,
    )

    npc = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={
            "type": "npc",
            "name": "Father Aldric",
            "visibility": "shared",
            "data": {
                "occupation": "Priest",
                "dm_players_think": "He is protecting the village.",
                "dm_notes": "He leads the cult feeding the artefact.",
            },
        },
        headers=dm,
    )
    eid = npc.json()["id"]
    assert npc.json()["data"]["dm_notes"].startswith("He leads")

    seen = (await client.get(f"{PREFIX}/campaigns/{cid}/entities/{eid}", headers=player)).json()
    assert seen["data"] == {"occupation": "Priest"}

    listed = (await client.get(f"{PREFIX}/campaigns/{cid}/entities", headers=player)).json()
    assert all("dm_notes" not in item["data"] for item in listed["items"])

    found = (await client.get(f"{PREFIX}/campaigns/{cid}/search?q=Aldric", headers=player)).json()
    assert all("dm_notes" not in hit["data"] for hit in found)


async def test_a_player_editing_their_sheet_keeps_the_dms_notes(client: AsyncClient):
    """`data` is replaced wholesale, and they never received the DM's half."""
    dm = await sign_up(client, "keepnotes-dm@example.com")
    player = await sign_up(client, "keepnotes-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "keepnotes-player@example.com", "role": "player"},
        headers=dm,
    )
    seat = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/players", json={"name": "Ana"}, headers=dm
        )
    ).json()
    await client.post(
        f"{PREFIX}/campaigns/{cid}/players/{seat['id']}/invite",
        json={"email": "keepnotes-player@example.com"},
        headers=dm,
    )

    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={
                "type": "character",
                "name": "Arannis",
                "player_id": seat["id"],
                "visibility": "shared",
                "data": {"current_hp": 27, "dm_notes": "Their brother is the villain."},
            },
            headers=dm,
        )
    ).json()

    # The player saves what they were given: their half, without the DM's
    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"data": {"current_hp": 12}},
        headers=player,
    )

    after = (
        await client.get(f"{PREFIX}/campaigns/{cid}/entities/{character['id']}", headers=dm)
    ).json()
    assert after["data"] == {"current_hp": 12, "dm_notes": "Their brother is the villain."}


async def test_a_player_cannot_write_dm_fields(client: AsyncClient):
    dm = await sign_up(client, "nowrite-dm@example.com")
    player = await sign_up(client, "nowrite-player@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "nowrite-player@example.com", "role": "player"},
        headers=dm,
    )

    character = (
        await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": "character", "name": "Theirs"},
            headers=player,
        )
    ).json()

    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{character['id']}",
        json={"data": {"level": 2, "dm_notes": "I write the secrets now"}},
        headers=player,
    )

    after = (
        await client.get(f"{PREFIX}/campaigns/{cid}/entities/{character['id']}", headers=dm)
    ).json()
    assert after["data"] == {"level": 2}
