"""match_jobs: seen/applied/dismissed timestamps

Revision ID: e6a4c3d9f125
Revises: 18efe4e45083
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6a4c3d9f125"
down_revision: Union[str, Sequence[str], None] = "18efe4e45083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("seen_at", "applied_at", "dismissed_at")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("match_jobs", sa.Column(name, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("match_jobs", name)
