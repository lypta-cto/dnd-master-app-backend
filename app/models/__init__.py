"""Importing every model here is what makes Alembic autogenerate see them."""

from app.models.base import Base
from app.models.campaign import Campaign, CampaignMember, CampaignRole
from app.models.cast import CastMode, CastState
from app.models.combat import CombatState
from app.models.entity import Entity, EntityLink, EntityType, LinkRelation, Visibility
from app.models.entity_image import EntityImage
from app.models.player import Player
from app.models.refresh_token import RefreshToken
from app.models.run import RunState
from app.models.user import Role, User
from app.models.workspace import Workspace

__all__ = [
    "Base",
    "Campaign",
    "CampaignMember",
    "CampaignRole",
    "CastMode",
    "CastState",
    "CombatState",
    "Entity",
    "EntityImage",
    "Player",
    "RunState",
    "EntityLink",
    "EntityType",
    "LinkRelation",
    "RefreshToken",
    "Role",
    "User",
    "Visibility",
    "Workspace",
]
