import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Combatant(BaseModel):
    """One row in the initiative order. `id` is client-generated — the list is
    a working set, not a table."""

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["character", "monster", "custom"] = "custom"
    entity_id: uuid.UUID | None = None
    initiative: int = Field(default=0, ge=-10, le=50)
    max_hp: int | None = Field(default=None, ge=0, le=9999)
    current_hp: int | None = Field(default=None, ge=0, le=9999)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    # Where the token sits, as percentages of the map. Absent means "not
    # placed yet" rather than "top-left corner", which is why these are
    # nullable instead of defaulting to zero.
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)


class CombatUpdate(BaseModel):
    active: bool = False
    #: The map the fight is on, if any
    map_id: uuid.UUID | None = None
    round: int = Field(default=1, ge=1, le=999)
    turn_index: int = Field(default=0, ge=0)
    combatants: list[Combatant] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _turn_in_range(self) -> "CombatUpdate":
        if self.combatants and self.turn_index >= len(self.combatants):
            raise ValueError("turn_index is past the end of the combatant list")
        return self


class CombatRead(CombatUpdate):
    model_config = ConfigDict(from_attributes=True)
