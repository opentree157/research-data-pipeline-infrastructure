"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sensor_id", sa.String(50), nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("humidity", sa.Float, nullable=False),
        sa.Column("pressure", sa.Float, nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_sensor_readings_timestamp", "sensor_readings", ["timestamp"])
    op.create_index("ix_sensor_readings_sensor_id", "sensor_readings", ["sensor_id"])

    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "sensor_data_id",
            sa.Integer,
            sa.ForeignKey("sensor_readings.id"),
            nullable=False,
        ),
        sa.Column("anomaly_type", sa.String(50), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_anomalies_sensor_data_id", "anomalies", ["sensor_data_id"])


def downgrade() -> None:
    op.drop_table("anomalies")
    op.drop_table("sensor_readings")
