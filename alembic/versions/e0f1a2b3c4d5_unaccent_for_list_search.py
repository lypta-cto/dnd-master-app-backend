"""unaccent, so a list search finds Serbian names typed without diacritics

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nobody types "Kovač" with the caron while hunting a name in a list of two
    # hundred, and a search that answers "no matches" to a name that is plainly
    # there reads as broken. The extension's default rules fold the whole Latin
    # set — č ć š ž đ included — so this covers more than Serbian.
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    # Left in place on purpose: dropping an extension another table or index
    # may have started using is not this migration's call to make.
    pass
