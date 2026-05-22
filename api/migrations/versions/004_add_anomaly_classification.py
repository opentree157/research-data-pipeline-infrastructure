"""Add anomaly classification and z-score columns

Revision ID: 004
Revises: 003
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anomalies", sa.Column("category", sa.String(30), nullable=True))
    op.add_column("anomalies", sa.Column("z_score", sa.Float, nullable=True))
    op.add_column("anomalies", sa.Column("rolling_mean", sa.Float, nullable=True))
    op.add_column("anomalies", sa.Column("rolling_std", sa.Float, nullable=True))
    op.add_column("anomalies", sa.Column("actual_value", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("anomalies", "actual_value")
    op.drop_column("anomalies", "rolling_std")
    op.drop_column("anomalies", "rolling_mean")
    op.drop_column("anomalies", "z_score")
    op.drop_column("anomalies", "category")
