from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    tagline: str | None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=255)
