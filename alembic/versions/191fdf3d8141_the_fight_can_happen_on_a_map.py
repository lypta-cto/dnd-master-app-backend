"""the fight can happen on a map

Revision ID: 191fdf3d8141
Revises: 6c552cfc1185
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "191fdf3d8141"
down_revision: str | None = "6c552cfc1185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately not a foreign key. Deleting a map mid-session should cost
    # the DM their battle map, not cascade into the fight the table is in the
    # middle of — the same reasoning as the session and scene ids on run_states.
    op.add_column("combat_states", sa.Column("map_id", sa.Uuid(), nullable=True))

    # Token positions live inside the existing combatants JSONB, so there is
    # nothing to add for them.


def downgrade() -> None:
    op.drop_column("combat_states", "map_id")
