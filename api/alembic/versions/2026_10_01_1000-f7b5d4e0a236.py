"""match_outputs: seniority

Revision ID: f7b5d4e0a236
Revises: e6a4c3d9f125
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7b5d4e0a236"
down_revision: Union[str, Sequence[str], None] = "e6a4c3d9f125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("match_outputs", sa.Column("seniority", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("match_outputs", "seniority")
