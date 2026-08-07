from httpx import AsyncClient

from app.core.config import settings
from tests.test_campaign import make_campaign, sign_up

PREFIX = settings.API_V1_PREFIX


async def test_cast_starts_idle(client: AsyncClient):
    dm = await sign_up(client, "cast1@example.com")
    cid = (await make_campaign(client, dm))["id"]

    response = await client.get(f"{PREFIX}/campaigns/{cid}/cast", headers=dm)

    assert response.status_code == 200
    assert response.json()["mode"] == "idle"
    assert response.json()["displays_connected"] == 0


async def test_dm_can_cast_an_image(client: AsyncClient):
    dm = await sign_up(client, "cast2@example.com")
    cid = (await make_campaign(client, dm))["id"]

    response = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={
            "mode": "image",
            "payload": {"image_url": "/uploads/keep.webp", "caption": "The keep"},
        },
        headers=dm,
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "image"
    assert response.json()["payload"]["caption"] == "The keep"


async def test_image_mode_without_an_image_is_rejected(client: AsyncClient):
    dm = await sign_up(client, "cast3@example.com")
    cid = (await make_campaign(client, dm))["id"]

    # Better to fail here than to blank the table's screen mid-session
    response = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast", json={"mode": "image", "payload": {}}, headers=dm
    )

    assert response.status_code == 422


async def test_players_cannot_cast(client: AsyncClient):
    dm = await sign_up(client, "cast4@example.com")
    await sign_up(client, "castplayer@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "castplayer@example.com", "role": "player"},
        headers=dm,
    )
    token = (
        await client.post(
            f"{PREFIX}/auth/login",
            json={"email": "castplayer@example.com", "password": "supersecret1"},
        )
    ).json()["access_token"]

    response = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={"mode": "text", "payload": {"text": "hi"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


# --- The display side --------------------------------------------------------


async def test_display_reads_without_logging_in(client: AsyncClient):
    dm = await sign_up(client, "cast5@example.com")
    campaign = await make_campaign(client, dm)
    cid, token = campaign["id"], campaign["display_token"]

    await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={"mode": "text", "payload": {"text": "Roll initiative"}},
        headers=dm,
    )

    # No Authorization header at all — a TV isn't a person
    response = await client.get(f"{PREFIX}/cast/{cid}", params={"t": token})

    assert response.status_code == 200
    assert response.json()["payload"]["text"] == "Roll initiative"


async def test_a_wrong_display_token_reveals_nothing(client: AsyncClient):
    dm = await sign_up(client, "cast6@example.com")
    cid = (await make_campaign(client, dm))["id"]

    response = await client.get(f"{PREFIX}/cast/{cid}", params={"t": "not-the-token"})

    assert response.status_code == 404


async def test_display_token_is_dm_only(client: AsyncClient):
    dm = await sign_up(client, "cast7@example.com")
    await sign_up(client, "castplayer2@example.com")
    campaign = await make_campaign(client, dm)
    cid = campaign["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "castplayer2@example.com", "role": "player"},
        headers=dm,
    )
    token = (
        await client.post(
            f"{PREFIX}/auth/login",
            json={"email": "castplayer2@example.com", "password": "supersecret1"},
        )
    ).json()["access_token"]

    seen = await client.get(
        f"{PREFIX}/campaigns/{cid}", headers={"Authorization": f"Bearer {token}"}
    )

    # The token is a credential; a player has no business holding it
    assert seen.status_code == 200
    assert seen.json()["display_token"] is None


async def test_rotating_the_token_invalidates_the_old_link(client: AsyncClient):
    dm = await sign_up(client, "cast8@example.com")
    campaign = await make_campaign(client, dm)
    cid, old_token = campaign["id"], campaign["display_token"]

    rotated = await client.post(f"{PREFIX}/campaigns/{cid}/display-token", headers=dm)
    new_token = rotated.json()["display_token"]

    assert new_token != old_token
    assert (await client.get(f"{PREFIX}/cast/{cid}", params={"t": old_token})).status_code == 404
    assert (await client.get(f"{PREFIX}/cast/{cid}", params={"t": new_token})).status_code == 200


async def test_casting_does_not_change_visibility(client: AsyncClient):
    """Showing a portrait for a moment must not permanently reveal the entity."""
    from tests.test_campaign import make_entity

    dm = await sign_up(client, "cast9@example.com")
    cid = (await make_campaign(client, dm))["id"]

    secret = await make_entity(client, dm, cid, name="The Traitor", visibility="dm_only")

    await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={"mode": "image", "payload": {"image_url": "/uploads/traitor.webp"}},
        headers=dm,
    )

    still = await client.get(f"{PREFIX}/campaigns/{cid}/entities/{secret['id']}", headers=dm)
    assert still.json()["visibility"] == "dm_only"


async def test_slideshow_requires_images(client: AsyncClient):
    dm = await sign_up(client, "cast10@example.com")
    cid = (await make_campaign(client, dm))["id"]

    empty = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={"mode": "slideshow", "payload": {"images": []}},
        headers=dm,
    )
    assert empty.status_code == 422

    ok = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={
            "mode": "slideshow",
            "payload": {
                "images": [
                    {"image_url": "/uploads/a.webp", "caption": "The keep"},
                    {"image_url": "/uploads/b.webp"},
                ],
                "interval_seconds": 6,
            },
        },
        headers=dm,
    )
    assert ok.status_code == 200
    assert ok.json()["mode"] == "slideshow"
    assert len(ok.json()["payload"]["images"]) == 2


async def test_dice_cast_carries_a_valid_roll(client: AsyncClient):
    dm = await sign_up(client, "cast11@example.com")
    cid = (await make_campaign(client, dm))["id"]

    bad = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={"mode": "dice", "payload": {"formula": "2d6"}},
        headers=dm,
    )
    assert bad.status_code == 422

    ok = await client.put(
        f"{PREFIX}/campaigns/{cid}/cast",
        json={
            "mode": "dice",
            "payload": {"formula": "2d6+3", "rolls": [4, 2], "modifier": 3, "total": 9,
                        "label": "Goblin attack"},
        },
        headers=dm,
    )
    assert ok.status_code == 200
    assert ok.json()["payload"]["total"] == 9
