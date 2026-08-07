from httpx import AsyncClient

from app.core.config import settings

PREFIX = settings.API_V1_PREFIX


async def sign_up(client: AsyncClient, email: str) -> dict[str, str]:
    """Returns an Authorization header for a fresh account."""
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "supersecret1", "full_name": email.split("@")[0]},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def make_campaign(client: AsyncClient, headers: dict[str, str], name="Curse of Strahd"):
    response = await client.post(f"{PREFIX}/campaigns", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()


async def make_entity(client, headers, campaign_id, **overrides):
    payload = {"type": "npc", "name": "Goblin King", "visibility": "dm_only", **overrides}
    response = await client.post(
        f"{PREFIX}/campaigns/{campaign_id}/entities", json=payload, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- Campaigns ---------------------------------------------------------------


async def test_creating_a_campaign_makes_you_its_dm(client: AsyncClient):
    headers = await sign_up(client, "dm@example.com")
    campaign = await make_campaign(client, headers)

    assert campaign["my_role"] == "dm"
    assert campaign["slug"] == "curse-of-strahd"
    assert campaign["display_token"]


async def test_campaigns_are_scoped_to_their_members(client: AsyncClient):
    dm = await sign_up(client, "dm2@example.com")
    stranger = await sign_up(client, "stranger@example.com")
    campaign = await make_campaign(client, dm)

    listed = await client.get(f"{PREFIX}/campaigns", headers=stranger)
    assert listed.json() == []

    # 404 rather than 403 — a stranger shouldn't learn the campaign exists
    direct = await client.get(f"{PREFIX}/campaigns/{campaign['id']}", headers=stranger)
    assert direct.status_code == 404


async def test_slugs_are_deduplicated(client: AsyncClient):
    headers = await sign_up(client, "dm3@example.com")
    first = await make_campaign(client, headers, name="Lost Mine")
    second = await make_campaign(client, headers, name="Lost Mine")

    assert first["slug"] == "lost-mine"
    assert second["slug"] == "lost-mine-2"


# --- Entities and links ------------------------------------------------------


async def test_wiki_links_become_real_links_and_backlinks(client: AsyncClient):
    headers = await sign_up(client, "dm4@example.com")
    campaign = await make_campaign(client, headers)
    cid = campaign["id"]

    keep = await make_entity(client, headers, cid, type="location", name="Blackmoor Keep")
    king = await make_entity(
        client,
        headers,
        cid,
        name="Goblin King",
        body="Fled toward [[Blackmoor Keep]] at dawn.",
    )

    assert [link["name"] for link in king["links"]] == ["Blackmoor Keep"]
    assert king["links"][0]["relation"] == "mentions"

    # The target gets the reverse view for free
    detail = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{keep['id']}", headers=headers
    )
    assert [b["name"] for b in detail.json()["backlinks"]] == ["Goblin King"]


async def test_unresolved_wiki_links_are_reported_not_dropped(client: AsyncClient):
    headers = await sign_up(client, "dm5@example.com")
    cid = (await make_campaign(client, headers))["id"]

    entity = await make_entity(
        client, headers, cid, body="Guarded by the [[Crown of Ash]], wherever that is."
    )

    assert entity["links"] == []
    assert entity["unresolved_links"] == ["Crown of Ash"]


async def test_links_reconnect_when_the_target_appears_later(client: AsyncClient):
    headers = await sign_up(client, "dm6@example.com")
    cid = (await make_campaign(client, headers))["id"]

    king = await make_entity(client, headers, cid, body="Wants the [[Crown of Ash]].")
    assert king["unresolved_links"] == ["Crown of Ash"]

    await make_entity(client, headers, cid, type="item", name="Crown of Ash")

    # Re-saving re-resolves; nothing else had to know
    updated = await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{king['id']}",
        json={"body": "Wants the [[Crown of Ash]]."},
        headers=headers,
    )
    body = updated.json()
    assert [link["name"] for link in body["links"]] == ["Crown of Ash"]
    assert body["unresolved_links"] == []


async def test_case_insensitive_wiki_links(client: AsyncClient):
    headers = await sign_up(client, "dm7@example.com")
    cid = (await make_campaign(client, headers))["id"]

    await make_entity(client, headers, cid, type="location", name="Blackmoor Keep")
    entity = await make_entity(
        client, headers, cid, name="Scout", body="Saw it at [[blackmoor keep]]."
    )

    assert [link["name"] for link in entity["links"]] == ["Blackmoor Keep"]


# --- Search ------------------------------------------------------------------


async def test_search_spans_every_type_in_one_query(client: AsyncClient):
    headers = await sign_up(client, "dm8@example.com")
    cid = (await make_campaign(client, headers))["id"]

    await make_entity(client, headers, cid, type="npc", name="Blackmoor Warden")
    await make_entity(client, headers, cid, type="location", name="Blackmoor Keep")
    await make_entity(client, headers, cid, type="item", name="Sword of Dawn")

    response = await client.get(
        f"{PREFIX}/campaigns/{cid}/search", params={"q": "blackmoor"}, headers=headers
    )
    names = {hit["name"] for hit in response.json()}

    assert names == {"Blackmoor Warden", "Blackmoor Keep"}


async def test_search_ranks_the_name_above_a_passing_mention(client: AsyncClient):
    headers = await sign_up(client, "dm9@example.com")
    cid = (await make_campaign(client, headers))["id"]

    await make_entity(client, headers, cid, type="note", name="Session 4 recap",
                      body="We finally reached Blackmoor after three days.")
    await make_entity(client, headers, cid, type="location", name="Blackmoor Keep")

    response = await client.get(
        f"{PREFIX}/campaigns/{cid}/search", params={"q": "blackmoor"}, headers=headers
    )
    hits = response.json()

    assert hits[0]["name"] == "Blackmoor Keep"


# --- Visibility --------------------------------------------------------------


async def test_players_never_see_dm_only_entities(client: AsyncClient):
    dm = await sign_up(client, "dm10@example.com")
    player = await sign_up(client, "player@example.com")
    campaign = await make_campaign(client, dm)
    cid = campaign["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "player@example.com", "role": "player"},
        headers=dm,
    )

    secret = await make_entity(client, dm, cid, name="The Traitor", visibility="dm_only")
    await make_entity(client, dm, cid, name="Village Elder", visibility="shared")

    listed = await client.get(f"{PREFIX}/campaigns/{cid}/entities", headers=player)
    assert [item["name"] for item in listed.json()["items"]] == ["Village Elder"]

    # Not in search either
    found = await client.get(
        f"{PREFIX}/campaigns/{cid}/search", params={"q": "traitor"}, headers=player
    )
    assert found.json() == []

    # And a direct id lookup can't confirm it exists
    direct = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{secret['id']}", headers=player
    )
    assert direct.status_code == 404


async def test_players_cannot_write(client: AsyncClient):
    dm = await sign_up(client, "dm11@example.com")
    await sign_up(client, "player2@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "player2@example.com", "role": "player"},
        headers=dm,
    )
    player = {"Authorization": (await client.post(
        f"{PREFIX}/auth/login",
        json={"email": "player2@example.com", "password": "supersecret1"},
    )).json()["access_token"]}
    player = {"Authorization": f"Bearer {player['Authorization']}"}

    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities",
        json={"type": "npc", "name": "Sneaky Insert"},
        headers=player,
    )
    assert response.status_code == 403


async def test_the_truth_behind_the_premise_stays_with_the_dm(client: AsyncClient):
    """`dm_` keys are the campaign's secrets — the API drops them for players."""
    dm = await sign_up(client, "setup-dm@example.com")
    player = await sign_up(client, "setup-player@example.com")

    campaign = await client.post(
        f"{PREFIX}/campaigns",
        json={
            "name": "Ravenford",
            "data": {
                "campaign_type": "one_shot",
                "premise": "People vanish from the village every night.",
                "player_intro": "The road ends at a shuttered inn.",
                "dm_truth": "The monster is trying to stop the ritual.",
                "dm_twist": "The priest leads the cult.",
            },
        },
        headers=dm,
    )
    cid = campaign.json()["id"]
    assert campaign.json()["data"]["dm_truth"].startswith("The monster")

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "setup-player@example.com", "role": "player"},
        headers=dm,
    )

    seen = (await client.get(f"{PREFIX}/campaigns/{cid}", headers=player)).json()["data"]
    assert seen["premise"].startswith("People vanish")
    assert "dm_truth" not in seen
    assert "dm_twist" not in seen

    # …and not through the list either
    listed = (await client.get(f"{PREFIX}/campaigns", headers=player)).json()
    assert all("dm_truth" not in c["data"] for c in listed)


async def test_campaign_setup_survives_an_edit(client: AsyncClient):
    dm = await sign_up(client, "setup-edit@example.com")
    cid = (await make_campaign(client, dm))["id"]

    updated = await client.patch(
        f"{PREFIX}/campaigns/{cid}",
        json={"data": {"tone": "dark", "system": "D&D 5e"}},
        headers=dm,
    )
    assert updated.status_code == 200
    assert updated.json()["data"] == {"tone": "dark", "system": "D&D 5e"}


async def test_scenes_encounters_and_clues_are_just_entities(client: AsyncClient):
    """New types cost an enum value — no new table, no new CRUD."""
    dm = await sign_up(client, "flow-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]

    for kind in ("scene", "encounter", "clue"):
        made = await client.post(
            f"{PREFIX}/campaigns/{cid}/entities",
            json={"type": kind, "name": f"A {kind}", "data": {"kind": "investigation"}},
            headers=dm,
        )
        assert made.status_code == 201, made.text
        assert made.json()["type"] == kind


async def test_a_scene_leads_to_another_and_survives_an_edit(client: AsyncClient):
    """`leads_to` is the flowchart, so a body edit must not sweep it away."""
    dm = await sign_up(client, "leads-dm@example.com")
    cid = (await make_campaign(client, dm))["id"]

    arrival = await make_entity(client, dm, cid, type="scene", name="Arrival at Ravenford")
    mill = await make_entity(client, dm, cid, type="scene", name="The Old Mill")

    linked = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities/{arrival['id']}/links",
        json={"to_id": mill["id"], "relation": "leads_to"},
        headers=dm,
    )
    assert linked.status_code == 201, linked.text

    # Rewriting the body rewrites `mentions` — nothing else
    await client.patch(
        f"{PREFIX}/campaigns/{cid}/entities/{arrival['id']}",
        json={"body": "The party arrives after dark."},
        headers=dm,
    )

    detail = (
        await client.get(f"{PREFIX}/campaigns/{cid}/entities/{arrival['id']}", headers=dm)
    ).json()
    assert [(link["name"], link["relation"]) for link in detail["links"]] == [
        ("The Old Mill", "leads_to")
    ]

    # …and the destination knows what leads to it
    back = (
        await client.get(f"{PREFIX}/campaigns/{cid}/entities/{mill['id']}", headers=dm)
    ).json()
    assert [link["name"] for link in back["backlinks"]] == ["Arrival at Ravenford"]
