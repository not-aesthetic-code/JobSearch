import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobsearch.database.base import Base

if TYPE_CHECKING:
    from jobsearch.database.models.match_output import MatchOutput

MatchJobStatus = Literal["pending", "processing", "completed", "failed"]
MATCH_JOB_STATUSES: tuple[str, ...] = get_args(MatchJobStatus)


class MatchJob(Base):
    """One LLM scoring job per (user, job_posting) pair. Mirrors deckard's
    LLMProcessingJob status lifecycle — kept separate from MatchOutput so a
    retry doesn't require re-shaping the result row."""

    __tablename__ = "match_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in MATCH_JOB_STATUSES) + ")",
            name="ck_match_jobs_status",
        ),
        UniqueConstraint("user_id", "job_posting_id", name="uq_match_jobs_user_id_job_posting_id"),
        Index("ix_match_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # the user's own triage of the shortlist entry: clicked through, applied, or hidden
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    output: Mapped["MatchOutput | None"] = relationship(
        back_populates="match_job", uselist=False, passive_deletes=True
    )
