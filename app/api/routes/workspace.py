from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, require_role
from app.models.user import Role
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceRead, WorkspaceUpdate

router = APIRouter(prefix="/workspace", tags=["workspace"])


async def get_or_create(session: SessionDep) -> Workspace:
    """One row, created on first read — no seeding step to forget."""
    result = await session.execute(select(Workspace).limit(1))
    workspace = result.scalar_one_or_none()

    if workspace is None:
        workspace = Workspace(name="DM Master")
        session.add(workspace)
        await session.flush()

    return workspace


@router.get("", response_model=WorkspaceRead)
async def read_workspace(session: SessionDep) -> WorkspaceRead:
    """Public: the login screen needs the app name and tagline before anyone
    has signed in. This is branding, not data."""
    return WorkspaceRead.model_validate(await get_or_create(session))


@router.patch(
    "",
    response_model=WorkspaceRead,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_workspace(payload: WorkspaceUpdate, session: SessionDep) -> WorkspaceRead:
    workspace = await get_or_create(session)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(workspace, field, value)

    await session.flush()
    return WorkspaceRead.model_validate(workspace)
