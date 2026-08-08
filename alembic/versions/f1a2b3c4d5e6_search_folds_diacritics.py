"""search folds diacritics, so "kovac" finds "Kovač" everywhere and not just in lists

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VECTOR = """
    setweight(to_tsvector('simple', immutable_unaccent(coalesce(name, ''))), 'A') ||
    setweight(to_tsvector('simple', immutable_unaccent(coalesce(summary, ''))), 'B') ||
    setweight(to_tsvector('simple', immutable_unaccent(coalesce(body, ''))), 'C')
"""

OLD_VECTOR = """
    setweight(to_tsvector('simple', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(summary, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(body, '')), 'C')
"""


def upgrade() -> None:
    # The list filter already folded diacritics; campaign search didn't, so the
    # same typed word found a name in one place and missed it in the other.
    #
    # `unaccent` can't go straight into a generated column: Postgres requires
    # IMMUTABLE there, and unaccent is only STABLE because it reads a
    # dictionary that could in principle be changed. Pinning the dictionary by
    # name makes the call genuinely deterministic, which is what the wrapper
    # exists to declare.
    op.execute("""
        CREATE OR REPLACE FUNCTION immutable_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS
        $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
    """)

    # A generated column can't be altered in place, so it's rebuilt — and the
    # index with it, since dropping the column takes the index along.
    op.execute("ALTER TABLE entities DROP COLUMN search_vector")
    op.execute(f"""
        ALTER TABLE entities
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({VECTOR}) STORED NOT NULL
    """)
    op.execute("CREATE INDEX ix_entities_search ON entities USING GIN (search_vector)")


def downgrade() -> None:
    op.execute("ALTER TABLE entities DROP COLUMN search_vector")
    op.execute(f"""
        ALTER TABLE entities
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS ({OLD_VECTOR}) STORED NOT NULL
    """)
    op.execute("CREATE INDEX ix_entities_search ON entities USING GIN (search_vector)")
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
