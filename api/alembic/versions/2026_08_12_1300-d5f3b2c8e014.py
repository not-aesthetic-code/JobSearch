"""add resume_chunks

Revision ID: d5f3b2c8e014
Revises: c4e2a1b7d903
Create Date: 2026-08-12 13:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'd5f3b2c8e014'
down_revision: Union[str, Sequence[str], None] = 'c4e2a1b7d903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'resume_chunks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('resume_id', sa.Uuid(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resume_id', 'chunk_index', name='uq_resume_chunks_resume_id_chunk_index'),
    )
    op.create_index(op.f('ix_resume_chunks_resume_id'), 'resume_chunks', ['resume_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_resume_chunks_resume_id'), table_name='resume_chunks')
    op.drop_table('resume_chunks')
