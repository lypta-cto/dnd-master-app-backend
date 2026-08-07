import uuid

from pydantic import BaseModel, ConfigDict, Field


class ClockEvent(BaseModel):
    """Something that happens at a time, whether or not the party is there."""

    label: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=300)
    done: bool = False


class RunUpdate(BaseModel):
    active: bool = False
    session_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None = None
    revealed: list[uuid.UUID] = Field(default_factory=list, max_length=300)
    # player id → how many times they've had the spotlight
    spotlight: dict[uuid.UUID, int] = Field(default_factory=dict)
    clock: list[ClockEvent] = Field(default_factory=list, max_length=60)
    notes: str | None = Field(default=None, max_length=5000)


class RunRead(RunUpdate):
    model_config = ConfigDict(from_attributes=True)
