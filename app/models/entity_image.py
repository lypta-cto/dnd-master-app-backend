import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class EntityImage(UUIDMixin, TimestampMixin, Base):
    """
    One row per uploaded image, many per entity — portrait, battle art, the
    room's floor plan. `Entity.image_url` stays as the cover shown in lists;
    it points at one of these (or nothing).

    Rows own their files: deleting a row deletes exactly that file, which is
    why the "wipe everything with this prefix" cleanup used for avatars is
    wrong here.
    """

    __tablename__ = "entity_images"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), index=True, nullable=False
    )

    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(300))

    # Manual ordering for the gallery and anything built from it
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
