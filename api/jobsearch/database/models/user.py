import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from jobsearch.database.base import Base


class User(Base):
    """One row per end user. `client_identifier` is the id from whatever auth
    the frontend uses (Clerk, etc.) — kept opaque here so swapping auth
    providers later doesn't touch this table."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    client_identifier: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
