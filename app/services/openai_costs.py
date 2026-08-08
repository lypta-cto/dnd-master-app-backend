"""What OpenAI says it actually billed.

Our own ledger adds up what each generation reported costing. This is the
other side of the same question, straight from the provider, so the two can be
compared and drift noticed rather than discovered on a statement.

Two things it is not, and both matter when reading the number:

It is **not the remaining balance**. OpenAI publishes no endpoint for that at
all — the dashboard is the only place it exists, which is a standing and
unanswered request from their developer community.

It is **organisation-wide**. The costs API reports what the account spent, not
what this campaign spent, so anything else using the same OpenAI account is in
the figure too. That makes it a sanity check against our ledger, never a
replacement for it.
"""

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

COSTS_URL = "https://api.openai.com/v1/organization/costs"


def configured() -> bool:
    """A separate, admin-scoped key — the project key cannot read billing."""
    return bool(settings.OPENAI_ADMIN_KEY)


async def spent_since(days: int = 30) -> dict[str, float | str]:
    """Total billed over the last `days`, in dollars, per the provider."""
    if not settings.OPENAI_ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set OPENAI_ADMIN_KEY to read what OpenAI actually billed.",
        )

    start = int((datetime.now(UTC) - timedelta(days=days)).timestamp())

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                COSTS_URL,
                headers={"Authorization": f"Bearer {settings.OPENAI_ADMIN_KEY}"},
                # Daily is the only bucket the endpoint offers; the limit is
                # buckets, not records, so a month needs 31 of them.
                params={"start_time": start, "bucket_width": "1d", "limit": 31},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't reach OpenAI's billing API.",
        ) from exc

    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("message", "Billing lookup failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    total = 0.0
    currency = "usd"

    for bucket in response.json().get("data", []):
        for result in bucket.get("results", []):
            amount = result.get("amount") or {}
            total += float(amount.get("value") or 0)
            currency = amount.get("currency") or currency

    return {"usd": round(total, 4), "currency": currency, "days": days}
