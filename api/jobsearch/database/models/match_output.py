import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobsearch.database.base import Base

if TYPE_CHECKING:
    from jobsearch.database.models.match_job import MatchJob


class MatchOutput(Base):
    """The single structured scoring result for a MatchJob. 1:1 via a unique FK."""

    __tablename__ = "match_outputs"
    __table_args__ = (CheckConstraint("score >= 0 AND score <= 100", name="ck_match_outputs_score_range"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    match_job: Mapped["MatchJob"] = relationship(back_populates="output")
