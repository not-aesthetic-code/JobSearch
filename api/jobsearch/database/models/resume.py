import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobsearch.database.base import Base

if TYPE_CHECKING:
    from jobsearch.database.models.user import User


class Resume(Base):
    """A user's resume as plain text. One user can have several versions; the
    most recent one is the profile CV used for matching. PDFs are turned into
    text at the edge (`endpoints/profile.py`) — this table never sees bytes."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # search keywords extracted from raw_text by the LLM; None until extraction runs
    keywords: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship()
