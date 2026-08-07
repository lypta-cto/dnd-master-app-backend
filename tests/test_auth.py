from httpx import AsyncClient

from app.core.config import settings

PREFIX = settings.API_V1_PREFIX
REGISTER = {"email": "user@example.com", "password": "supersecret1", "full_name": "Test User"}


async def register(client: AsyncClient, **overrides) -> dict:
    response = await client.post(f"{PREFIX}/auth/register", json={**REGISTER, **overrides})
    return response.json()


async def test_register_returns_token_and_sets_cookie(client: AsyncClient):
    response = await client.post(f"{PREFIX}/auth/register", json=REGISTER)

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == REGISTER["email"]
    assert body["user"]["role"] == "member"
    # The refresh token must never be in the body
    assert "refresh_token" not in body
    assert settings.REFRESH_COOKIE_NAME in response.cookies


async def test_register_rejects_duplicate_email(client: AsyncClient):
    await register(client)
    response = await client.post(f"{PREFIX}/auth/register", json=REGISTER)

    assert response.status_code == 409


async def test_login_with_correct_password(client: AsyncClient):
    await register(client)

    response = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": REGISTER["email"], "password": REGISTER["password"]},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_with_wrong_password_is_rejected(client: AsyncClient):
    await register(client)

    response = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": REGISTER["email"], "password": "wrong-password"},
    )

    assert response.status_code == 401
    # Same message as an unknown email, so accounts can't be enumerated
    assert response.json()["detail"] == "Incorrect email or password"


async def test_login_with_unknown_email_is_rejected(client: AsyncClient):
    response = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": "nobody@example.com", "password": "supersecret1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


async def test_me_requires_a_token(client: AsyncClient):
    response = await client.get(f"{PREFIX}/auth/me")

    assert response.status_code == 401


async def test_me_returns_the_current_user(client: AsyncClient):
    body = await register(client)

    response = await client.get(
        f"{PREFIX}/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == REGISTER["email"]


async def test_refresh_rotates_the_cookie(client: AsyncClient):
    await register(client)
    first_cookie = client.cookies[settings.REFRESH_COOKIE_NAME]

    response = await client.post(f"{PREFIX}/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert client.cookies[settings.REFRESH_COOKIE_NAME] != first_cookie


async def test_used_refresh_token_cannot_be_replayed(client: AsyncClient):
    await register(client)
    stolen = client.cookies[settings.REFRESH_COOKIE_NAME]

    await client.post(f"{PREFIX}/auth/refresh")  # rotates, revoking `stolen`

    client.cookies.set(settings.REFRESH_COOKIE_NAME, stolen)
    response = await client.post(f"{PREFIX}/auth/refresh")

    assert response.status_code == 401


async def test_refresh_without_a_cookie_is_rejected(client: AsyncClient):
    response = await client.post(f"{PREFIX}/auth/refresh")

    assert response.status_code == 401


async def test_logout_revokes_the_session(client: AsyncClient):
    await register(client)

    logout = await client.post(f"{PREFIX}/auth/logout")
    assert logout.status_code == 200

    response = await client.post(f"{PREFIX}/auth/refresh")
    assert response.status_code == 401


async def test_members_cannot_reach_admin_routes(client: AsyncClient):
    body = await register(client)

    response = await client.get(
        f"{PREFIX}/users",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert response.status_code == 403


async def test_health_is_public(client: AsyncClient):
    response = await client.get("/health")

    # Health probes the real engine on purpose — a monitor wants to know about
    # the actual database, not an injected test session. So the suite asserts
    # it needs no auth and reports its findings, not that the DB happens to be
    # up while the tests run.
    assert response.status_code in (200, 503)

    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert body["database"] in ("ok", "unavailable")
