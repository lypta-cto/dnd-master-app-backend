"""the purse: what generation costs, in coins

Revision ID: 6c552cfc1185
Revises: f1a2b3c4d5e6

Autogenerate also offered a handful of changes to `players` and `run_states` —
nullability and an index that earlier hand-written migrations had left slightly
out of step with the models. They are unrelated to this table and dropping them
into a migration named after the purse would hide them; they belong in their
own change, deliberately, once someone has decided which side is right.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6c552cfc1185"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coin_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "entry_type",
            sa.Enum("topup", "text", "image", name="coin_entry_type"),
            nullable=False,
        ),
        # Millionths of a dollar, signed: a top-up adds, a generation takes
        # away. Coins are the display unit; the exact costs don't land on whole
        # ones, and rounding at write time would drift away from the real bill.
        sa.Column("micros", sa.BigInteger(), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_coin_entries_campaign_id"), "coin_entries", ["campaign_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_coin_entries_campaign_id"), table_name="coin_entries")
    op.drop_table("coin_entries")
    op.execute("DROP TYPE IF EXISTS coin_entry_type")
