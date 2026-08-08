import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CoinEntryType(StrEnum):
    TOPUP = "topup"
    TEXT = "text"
    IMAGE = "image"


class CoinEntry(Base, UUIDMixin, TimestampMixin):
    """One line of the purse: money put in, or a generation that spent some.

    Amounts are stored in millionths of a dollar rather than in coins, because
    coins are the display unit and the exact figures don't land on whole ones —
    a text draft costs 2.4 of them. Rounding at write time would quietly lose a
    fraction on every line and the total would drift away from the real bill.
    Convert once, at the edge, for the person reading it.
    """

    __tablename__ = "coin_entries"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Who spent it. Kept even after they leave, so the ledger stays complete.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    entry_type: Mapped[CoinEntryType] = mapped_column(
        Enum(CoinEntryType, name="coin_entry_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    # Signed: a top-up adds, a generation takes away. Summing the column is
    # then the balance, with no cases to remember.
    micros: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # What it was for, in the DM's terms: "Illustrated Stara vodenica (good)"
    detail: Mapped[str] = mapped_column(String(300), nullable=False, default="")
