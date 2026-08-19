import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Computed, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from jobsearch.database.base import Base

EMBED_DIM = 1536  # text-embedding-3-small; changing models means a migration + re-embed


class JobPosting(Base):
    """A job posting pulled from some source (a JSON API like RemoteOK, or a
    scraped page). `(source, source_id)` is the natural key — reruns of the
    same ingestion just upsert on it instead of duplicating rows."""

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_job_postings_source_source_id"),
        # declared here only so `alembic revision --autogenerate` doesn't decide
        # they're stray and drop them
        Index(
            "ix_job_postings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_job_postings_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    description_text: Mapped[str] = mapped_column(Text, nullable=False)

    # None = the source never said. Comes from schema.org jobLocationType on
    # scraped pages, so it's the employer's own claim, not a keyword guess.
    remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # retrieval channels: dense (embedding of title + description, None until
    # embed_new_postings runs) and lexical (maintained by Postgres, never written by us)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || description_text)", persisted=True),
        nullable=False,
    )
