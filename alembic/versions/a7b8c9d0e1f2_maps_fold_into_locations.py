"""Maps fold into their parent locations.

A map was its own entity type; it is an attribute of a location now — the
dungeon's floor plan belongs to the dungeon. Every map entity that stands
inside a location hands over its picture (data.map_image_url), pins, fog and
grid to that location, everything that pointed at the map is re-pointed at
the location, and the map entity goes. Maps with no location parent or no
picture are left alone: their pages still work in the legacy spelling.

Data-only; the schema doesn't change.

Revision ID: a7b8c9d0e1f2
Revises: 5e0b6b77a2e3
Create Date: 2026-08-10
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "5e0b6b77a2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            """
            SELECT m.id AS map_id, m.image_url, m.data AS map_data,
                   p.id AS parent_id, p.data AS parent_data
            FROM entities m
            JOIN entity_links l ON l.from_id = m.id AND l.relation = 'located_in'
            JOIN entities p ON p.id = l.to_id
            WHERE m.type = 'map' AND p.type = 'location'
              AND m.image_url IS NOT NULL
            """
        )
    ).mappings()

    for row in rows:
        parent_data = dict(row["parent_data"] or {})
        map_data = dict(row["map_data"] or {})

        # The parent's own map wins if it somehow already has one
        if not parent_data.get("map_image_url"):
            parent_data["map_image_url"] = row["image_url"]
            for key in ("pins", "fog", "grid"):
                if key in map_data and key not in parent_data:
                    parent_data[key] = map_data[key]

        bind.execute(
            sa.text("UPDATE entities SET data = :data WHERE id = :id"),
            {"data": json.dumps(parent_data), "id": row["parent_id"]},
        )

        # Whatever pointed at the map now points at the place it described
        bind.execute(
            sa.text("UPDATE combat_states SET map_id = :parent WHERE map_id = :old"),
            {"parent": row["parent_id"], "old": row["map_id"]},
        )
        bind.execute(
            sa.text(
                """
                UPDATE entities
                SET data = jsonb_set(data, '{map_id}', to_jsonb(CAST(:parent AS text)))
                WHERE type = 'encounter' AND data->>'map_id' = :old
                """
            ),
            {"parent": str(row["parent_id"]), "old": str(row["map_id"])},
        )

        # Links and gallery rows cascade with the entity
        bind.execute(
            sa.text("DELETE FROM entities WHERE id = :id"), {"id": row["map_id"]}
        )


def downgrade() -> None:
    # The map entities are gone; there is nothing faithful to rebuild them
    # from. The attribute form stays — it is strictly more information.
    pass
