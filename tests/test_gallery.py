import io

from httpx import AsyncClient
from PIL import Image

from app.core.config import settings
from tests.test_campaign import make_campaign, make_entity, sign_up

PREFIX = settings.API_V1_PREFIX


def png_bytes(colour: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(buffer, format="PNG")
    return buffer.getvalue()


async def upload(client, headers, cid, eid, colour="red", caption=None):
    data = {"caption": caption} if caption else {}
    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities/{eid}/images",
        files={"file": ("art.png", png_bytes(colour), "image/png")},
        data=data,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_first_gallery_image_becomes_the_cover(client: AsyncClient):
    dm = await sign_up(client, "gal1@example.com")
    cid = (await make_campaign(client, dm))["id"]
    entity = await make_entity(client, dm, cid, name="Strahd")

    image = await upload(client, dm, cid, entity["id"], caption="Portrait")

    detail = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{entity['id']}", headers=dm
    )
    assert detail.json()["image_url"] == image["url"]


async def test_deleting_one_image_keeps_the_others(client: AsyncClient):
    dm = await sign_up(client, "gal2@example.com")
    cid = (await make_campaign(client, dm))["id"]
    eid = (await make_entity(client, dm, cid, name="Keep"))["id"]

    first = await upload(client, dm, cid, eid, "red")
    second = await upload(client, dm, cid, eid, "blue")

    await client.delete(
        f"{PREFIX}/campaigns/{cid}/entities/{eid}/images/{first['id']}", headers=dm
    )

    remaining = await client.get(
        f"{PREFIX}/campaigns/{cid}/entities/{eid}/images", headers=dm
    )
    urls = [image["url"] for image in remaining.json()]
    assert urls == [second["url"]]

    # Cover fell back to the surviving image rather than dangling
    detail = await client.get(f"{PREFIX}/campaigns/{cid}/entities/{eid}", headers=dm)
    assert detail.json()["image_url"] == second["url"]


async def test_campaign_image_pool_respects_visibility(client: AsyncClient):
    dm = await sign_up(client, "gal3@example.com")
    await sign_up(client, "galplayer@example.com")
    cid = (await make_campaign(client, dm))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "galplayer@example.com", "role": "player"},
        headers=dm,
    )
    token = (
        await client.post(
            f"{PREFIX}/auth/login",
            json={"email": "galplayer@example.com", "password": "supersecret1"},
        )
    ).json()["access_token"]
    player = {"Authorization": f"Bearer {token}"}

    secret = await make_entity(client, dm, cid, name="Secret", visibility="dm_only")
    public = await make_entity(client, dm, cid, name="Public", visibility="shared")
    await upload(client, dm, cid, secret["id"], "red")
    await upload(client, dm, cid, public["id"], "blue")

    dm_pool = await client.get(f"{PREFIX}/campaigns/{cid}/images", headers=dm)
    assert {img["entity_name"] for img in dm_pool.json()} == {"Secret", "Public"}

    player_pool = await client.get(f"{PREFIX}/campaigns/{cid}/images", headers=player)
    assert {img["entity_name"] for img in player_pool.json()} == {"Public"}


async def test_players_cannot_upload_images(client: AsyncClient):
    dm = await sign_up(client, "gal4@example.com")
    await sign_up(client, "galplayer2@example.com")
    cid = (await make_campaign(client, dm))["id"]
    eid = (await make_entity(client, dm, cid, name="Open", visibility="shared"))["id"]

    await client.post(
        f"{PREFIX}/campaigns/{cid}/members",
        json={"email": "galplayer2@example.com", "role": "player"},
        headers=dm,
    )
    token = (
        await client.post(
            f"{PREFIX}/auth/login",
            json={"email": "galplayer2@example.com", "password": "supersecret1"},
        )
    ).json()["access_token"]

    response = await client.post(
        f"{PREFIX}/campaigns/{cid}/entities/{eid}/images",
        files={"file": ("art.png", png_bytes("green"), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
