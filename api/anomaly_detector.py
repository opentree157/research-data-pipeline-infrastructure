"""
Anomaly detection for sensor data.
Flags readings >2 standard deviations from a rolling mean.
Adapted from the provided reference implementation to work with SQLAlchemy models.
"""

import logging
from datetime import datetime, timezone
from typing import List

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config import ANOMALY_THRESHOLD, ROLLING_WINDOW_SIZE
from models import Anomaly, SensorReading

logger = logging.getLogger(__name__)

METRICS = ["temperature", "humidity", "pressure"]


def detect_anomalies(db: Session, reading_ids: List[int]) -> int:
    readings = (
        db.query(SensorReading)
        .filter(SensorReading.id.in_(reading_ids))
        .order_by(SensorReading.sensor_id, SensorReading.timestamp)
        .all()
    )
    if not readings:
        return 0

    rows = [
        {
            "id": r.id,
            "sensor_id": r.sensor_id,
            "timestamp": r.timestamp,
            "temperature": r.temperature,
            "humidity": r.humidity,
            "pressure": r.pressure,
        }
        for r in readings
    ]
    df = pd.DataFrame(rows).sort_values(["sensor_id", "timestamp"])

    anomalies: list[Anomaly] = []

    for sensor_id, sensor_df in df.groupby("sensor_id"):
        for metric in METRICS:
            rolling_mean = sensor_df[metric].rolling(
                window=ROLLING_WINDOW_SIZE, min_periods=1
            ).mean()
            rolling_std = sensor_df[metric].rolling(
                window=ROLLING_WINDOW_SIZE, min_periods=1
            ).std()

            z_scores = (sensor_df[metric] - rolling_mean) / rolling_std

            for idx in sensor_df[z_scores.abs() > ANOMALY_THRESHOLD].index:
                z = z_scores.loc[idx]
                if pd.isna(z):
                    continue
                anomalies.append(
                    Anomaly(
                        sensor_data_id=int(sensor_df.loc[idx, "id"]),
                        anomaly_type=f"{metric}_anomaly",
                        confidence_score=round(float(abs(z)), 4),
                        detected_at=datetime.now(timezone.utc),
                    )
                )

    if anomalies:
        db.bulk_save_objects(anomalies)
        db.commit()

    logger.info("Detected %d anomalies in %d readings", len(anomalies), len(readings))
    return len(anomalies)
