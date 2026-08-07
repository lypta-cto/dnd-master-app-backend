"""The health check answers for this process, not for its dependencies.

This one is worth a test because getting it wrong is invisible locally and
expensive in production: a host restarts a service whose health check fails,
and a serverless database suspends itself when idle. Answering 503 because the
database was asleep put the two in a loop — nap, fail, restart, nap — which
dropped roughly a third of all requests, killed every cast connection, and
turned an interrupted wizard into duplicate rows.
"""

from httpx import AsyncClient

from app.core.config import settings


async def test_health_is_ok_when_everything_is(client: AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_a_sleeping_database_does_not_make_this_process_unhealthy(
    client: AsyncClient, monkeypatch
):
    """Report it, don't fail on it — the next query wakes it up."""
    from app import main

    class Suspended:
        """What a serverless database looks like from here while it sleeps."""

        def connect(self):
            raise OSError("connection refused")

    monkeypatch.setattr(main, "engine", Suspended())

    response = await client.get("/health")

    # 200, or the host kills a process that is perfectly able to serve
    assert response.status_code == 200
    assert response.json()["database"] == "unavailable"
    # Still said out loud, because it's the first thing you want to know
    assert response.json()["status"] == "degraded"


async def test_interactive_docs_stop_at_production(client: AsyncClient):
    """They map every endpoint and payload — help while building, not in public."""
    expected = 404 if settings.ENVIRONMENT == "production" else 200

    assert (await client.get("/docs")).status_code == expected
