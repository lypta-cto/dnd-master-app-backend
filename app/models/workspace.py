from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Workspace(UUIDMixin, TimestampMixin, Base):
    """
    Settings that belong to the installation rather than to a person — the app
    name shown in the sidebar, the tagline on the login screen.

    Deliberately a single row. If you ever go multi-tenant, this is the table
    that grows a `slug` and stops being a singleton.
    """

    __tablename__ = "workspace"

    name: Mapped[str] = mapped_column(String(120), nullable=False, default="DM Master")
    tagline: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<Workspace {self.name}>"
