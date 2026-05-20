"""
Anomaly detection for sensor data.
Flags readings >2 standard deviations from a rolling mean.

Each run fetches the prior ROLLING_WINDOW_SIZE readings per sensor from the
database so that rolling statistics are correct across ingest boundaries.
Only newly ingested readings are evaluated for anomalies.
"""

import logging
from datetime import datetime, timezone
from typing import List

import pandas as pd
from sqlalchemy import and_
from sqlalchemy.orm import Session

from config import ANOMALY_THRESHOLD, ROLLING_WINDOW_SIZE
from models import Anomaly, SensorReading

logger = logging.getLogger(__name__)

METRICS = ["temperature", "humidity", "pressure"]


def _fetch_with_history(
    db: Session, reading_ids: List[int]
) -> tuple[pd.DataFrame, set[int]]:
    new_readings = (
        db.query(SensorReading)
        .filter(SensorReading.id.in_(reading_ids))
        .all()
    )
    if not new_readings:
        return pd.DataFrame(), set()

    new_id_set = set(reading_ids)
    sensor_ids = {r.sensor_id for r in new_readings}

    history = []
    for sid in sensor_ids:
        earliest_new = min(
            r.timestamp for r in new_readings if r.sensor_id == sid
        )
        prior = (
            db.query(SensorReading)
            .filter(
                and_(
                    SensorReading.sensor_id == sid,
                    SensorReading.timestamp < earliest_new,
                    ~SensorReading.id.in_(reading_ids),
                )
            )
            .order_by(SensorReading.timestamp.desc())
            .limit(ROLLING_WINDOW_SIZE)
            .all()
        )
        history.extend(prior)

    all_readings = history + new_readings
    rows = [
        {
            "id": r.id,
            "sensor_id": r.sensor_id,
            "timestamp": r.timestamp,
            "temperature": r.temperature,
            "humidity": r.humidity,
            "pressure": r.pressure,
        }
        for r in all_readings
    ]
    df = pd.DataFrame(rows).sort_values(["sensor_id", "timestamp"]).reset_index(drop=True)
    return df, new_id_set


def detect_anomalies(db: Session, reading_ids: List[int]) -> int:
    df, new_id_set = _fetch_with_history(db, reading_ids)
    if df.empty:
        return 0

    anomaly_rows: list[dict] = []

    for sensor_id, sensor_df in df.groupby("sensor_id"):
        for metric in METRICS:
            rolling_mean = sensor_df[metric].rolling(
                window=ROLLING_WINDOW_SIZE, min_periods=1
            ).mean()
            rolling_std = sensor_df[metric].rolling(
                window=ROLLING_WINDOW_SIZE, min_periods=1
            ).std()

            z_scores = (sensor_df[metric] - rolling_mean) / rolling_std

            for idx in sensor_df.index:
                row_id = int(sensor_df.loc[idx, "id"])
                if row_id not in new_id_set:
                    continue
                z = z_scores.loc[idx]
                if pd.isna(z) or abs(z) <= ANOMALY_THRESHOLD:
                    continue
                anomaly_rows.append(
                    {
                        "sensor_data_id": row_id,
                        "anomaly_type": f"{metric}_anomaly",
                        "confidence_score": round(float(abs(z)), 4),
                        "detected_at": datetime.now(timezone.utc),
                    }
                )

    if not anomaly_rows:
        logger.info("Detected 0 anomalies in %d readings", len(new_id_set))
        return 0

    dialect = db.bind.dialect.name if db.bind else "default"
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Anomaly).on_conflict_do_nothing(
            index_elements=["sensor_data_id", "anomaly_type"]
        )
        db.execute(stmt, anomaly_rows)
    else:
        for row in anomaly_rows:
            exists = (
                db.query(Anomaly)
                .filter_by(
                    sensor_data_id=row["sensor_data_id"],
                    anomaly_type=row["anomaly_type"],
                )
                .first()
            )
            if not exists:
                db.add(Anomaly(**row))
    db.commit()

    logger.info("Detected %d anomalies in %d readings", len(anomaly_rows), len(new_id_set))
    return len(anomaly_rows)
