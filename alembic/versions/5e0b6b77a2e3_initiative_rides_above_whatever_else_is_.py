"""initiative rides above whatever else is cast

Revision ID: 5e0b6b77a2e3
Revises: 191fdf3d8141
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e0b6b77a2e3"
down_revision: str | None = "191fdf3d8141"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Its own column rather than a key inside `payload`, because payload is
    # replaced whole on every cast. The order of turns has to outlive that:
    # while a fight is running it belongs above whatever is on screen, and
    # casting the battle map must not take it away.
    op.add_column(
        "cast_states",
        sa.Column(
            "initiative",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cast_states", "initiative")
