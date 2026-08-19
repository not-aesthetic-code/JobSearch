"""add pgvector + hybrid retrieval columns to job_postings

Revision ID: c4e2a1b7d903
Revises: b3c1d92f4a01
Create Date: 2026-08-12 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = 'c4e2a1b7d903'
down_revision: Union[str, Sequence[str], None] = 'b3c1d92f4a01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column('job_postings', sa.Column('embedding', Vector(1536), nullable=True))
    op.add_column(
        'job_postings',
        sa.Column(
            'search_vector',
            TSVECTOR,
            sa.Computed("to_tsvector('english', title || ' ' || description_text)", persisted=True),
            nullable=False,
        ),
    )

    # ponytail: both indexes are cosmetic below ~10k postings (Postgres just
    # seq-scans) — they exist so the query plan doesn't change shape later
    op.execute(
        "CREATE INDEX ix_job_postings_embedding_hnsw ON job_postings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index(
        'ix_job_postings_search_vector', 'job_postings', ['search_vector'], postgresql_using='gin'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_job_postings_search_vector', table_name='job_postings')
    op.execute("DROP INDEX ix_job_postings_embedding_hnsw")
    op.drop_column('job_postings', 'search_vector')
    op.drop_column('job_postings', 'embedding')
