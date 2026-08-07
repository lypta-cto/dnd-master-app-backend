"""
The cast channel.

One-way: the DM writes state, connected displays are told to re-read it. The
broker is in-memory, which is correct for a single process and wrong for
several — if this ever runs under more than one worker, swap `publish` and
`subscribe` for Postgres LISTEN/NOTIFY (asyncpg supports it, no new infra) or
Redis pub/sub. Nothing outside this module needs to change.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator

# campaign_id → the queues of everyone currently watching
_subscribers: dict[uuid.UUID, set[asyncio.Queue[str]]] = {}

# How long to wait before sending a comment line to keep the connection warm.
# Proxies and load balancers hang up on idle connections; a table can sit on one
# image for an hour.
HEARTBEAT_SECONDS = 20


def publish(campaign_id: uuid.UUID, event: str = "cast") -> None:
    """Non-blocking on purpose: a slow display must never hold up the DM's request."""
    for queue in _subscribers.get(campaign_id, set()):
        # A full queue means that display is already behind; it re-reads the
        # authoritative state on the next event it does receive.
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)


async def subscribe(campaign_id: uuid.UUID) -> AsyncGenerator[str, None]:
    """Yields SSE-formatted frames until the client goes away."""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=16)
    _subscribers.setdefault(campaign_id, set()).add(queue)

    try:
        # Tell the browser how long to wait before reconnecting, then nudge the
        # display to fetch the current state so it renders immediately rather
        # than waiting for the DM's next change.
        yield "retry: 3000\n\n"
        yield "event: cast\ndata: connected\n\n"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                yield f"event: {event}\ndata: changed\n\n"
            except TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        watchers = _subscribers.get(campaign_id)
        if watchers is not None:
            watchers.discard(queue)
            if not watchers:
                del _subscribers[campaign_id]


def subscriber_count(campaign_id: uuid.UUID) -> int:
    """Lets the DM see whether the table's screen is actually connected."""
    return len(_subscribers.get(campaign_id, set()))
