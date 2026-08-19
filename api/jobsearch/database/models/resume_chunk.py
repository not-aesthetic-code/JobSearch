import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobsearch.database.base import Base
from jobsearch.database.models.job_posting import EMBED_DIM

if TYPE_CHECKING:
    from jobsearch.database.models.resume import Resume


class ResumeChunk(Base):
    """A section of a resume, embedded so a job posting can retrieve the parts of
    the CV that actually answer it. Same embedding model as JobPosting.embedding —
    the two vector spaces have to match for cosine distance between them to mean
    anything.

    ponytail: no vector index — a resume is a couple of dozen rows, Postgres
    scans them faster than it reads an index."""

    __tablename__ = "resume_chunks"
    __table_args__ = (UniqueConstraint("resume_id", "chunk_index", name="uq_resume_chunks_resume_id_chunk_index"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)

    resume: Mapped["Resume"] = relationship()
