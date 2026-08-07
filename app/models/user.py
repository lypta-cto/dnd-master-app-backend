import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken


class Role(enum.StrEnum):
    """Ranked: every role implies the permissions of the ones before it.

    Mirrors the frontend's `can(role)` helper — keep the two in step.
    """

    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return _ROLE_ORDER.index(self)

    def can(self, minimum: "Role") -> bool:
        return self.rank >= minimum.rank


_ROLE_ORDER: list[Role] = [Role.VIEWER, Role.MEMBER, Role.ADMIN, Role.OWNER]


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))

    # Null for accounts that only ever signed in through an OAuth provider
    hashed_password: Mapped[str | None] = mapped_column(String(255))

    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        default=Role.MEMBER,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Set when the account is linked to Google
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def has_password(self) -> bool:
        return self.hashed_password is not None

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"
