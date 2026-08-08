"""The purse.

Generation costs real money in fractions of a cent, which is a terrible unit
to read a running total in. Coins are the readable one: a text draft is worth
about two, an illustration two dozen, a good illustration under ninety.

The rate is chosen so the cheapest thing the app does still costs more than
one coin. At a hundred coins to the dollar — the obvious first guess — a text
draft comes to 0.024 of one, every line of the ledger reads as zero, and the
feature tells you nothing.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coin import CoinEntry, CoinEntryType

#: Millionths of a dollar in one coin. 10,000 coins to the dollar.
MICROS_PER_COIN = 100

#: A dollar, in coins — the number the DM converts with in their head
COINS_PER_DOLLAR = 1_000_000 // MICROS_PER_COIN


def coins(micros: int) -> float:
    """Coins, to one decimal — a text draft is 2.4 of them and that's honest."""
    return round(micros / MICROS_PER_COIN, 1)


def micros_from_cents(cents: float) -> int:
    """Providers bill in cents; the ledger stores whole millionths."""
    return round(cents * 10_000)


async def record(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    user_id: uuid.UUID | None,
    entry_type: CoinEntryType,
    micros: int,
    detail: str,
) -> CoinEntry:
    """One line. Spending is stored negative so the balance is a plain SUM."""
    entry = CoinEntry(
        campaign_id=campaign_id,
        user_id=user_id,
        entry_type=entry_type,
        micros=micros,
        detail=detail[:300],
    )
    session.add(entry)
    return entry


async def summary(session: AsyncSession, campaign_id: uuid.UUID) -> dict[str, int]:
    """Balance and what each kind of generation has cost, all in micros."""
    rows = (
        await session.execute(
            select(CoinEntry.entry_type, func.coalesce(func.sum(CoinEntry.micros), 0))
            .where(CoinEntry.campaign_id == campaign_id)
            .group_by(CoinEntry.entry_type)
        )
    ).all()

    by_type = {entry_type: int(total) for entry_type, total in rows}

    # Spending is negative in the column; the DM wants to read it as a cost
    return {
        "balance": sum(by_type.values()),
        "added": by_type.get(CoinEntryType.TOPUP, 0),
        "text": -by_type.get(CoinEntryType.TEXT, 0),
        "image": -by_type.get(CoinEntryType.IMAGE, 0),
    }
