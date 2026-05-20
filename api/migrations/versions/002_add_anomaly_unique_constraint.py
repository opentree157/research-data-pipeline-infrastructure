"""Add unique constraint on (sensor_data_id, anomaly_type)

Revision ID: 002
Revises: 001
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_anomaly_reading_type", "anomalies", ["sensor_data_id", "anomaly_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_anomaly_reading_type", "anomalies", type_="unique")
