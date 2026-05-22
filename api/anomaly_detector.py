"""
Anomaly detection for sensor data.
Flags readings >2 standard deviations from a rolling mean and classifies
anomalies into categories: spike, sensor_failure, drift, noise_burst.
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

SENSOR_FAILURE_VALUES = {-999.0, 0.0}
SPIKE_Z_THRESHOLD = 5.0
DRIFT_WINDOW = 5


def _classify_anomaly(
    sensor_df: pd.DataFrame,
    idx: int,
    metric: str,
    z: float,
    value: float,
) -> str:
    if value in SENSOR_FAILURE_VALUES:
        return "sensor_failure"

    if abs(z) >= SPIKE_Z_THRESHOLD:
        return "spike"

    start = max(0, idx - DRIFT_WINDOW)
    window = sensor_df.iloc[start:idx + 1]
    if len(window) >= DRIFT_WINDOW:
        diffs = window[metric].diff().dropna()
        if (diffs > 0).all() or (diffs < 0).all():
            return "drift"

    metric_anomalies = 0
    for m in METRICS:
        if m == metric:
            continue
        m_val = sensor_df.loc[idx, m]
        if m_val in SENSOR_FAILURE_VALUES:
            continue
        m_mean = sensor_df[m].iloc[start:idx].mean() if idx > 0 else m_val
        m_std = sensor_df[m].iloc[start:idx].std() if idx > 1 else 0
        if m_std > 0 and abs(m_val - m_mean) > ANOMALY_THRESHOLD * m_std:
            metric_anomalies += 1
    if metric_anomalies >= 1:
        return "noise_burst"

    return "spike"


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
        sensor_df = sensor_df.reset_index(drop=True)
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

                value = float(sensor_df.loc[idx, metric])
                mean_val = float(rolling_mean.loc[idx])
                std_val = float(rolling_std.loc[idx])
                category = _classify_anomaly(sensor_df, idx, metric, z, value)

                anomaly_rows.append(
                    {
                        "sensor_data_id": row_id,
                        "anomaly_type": f"{metric}_anomaly",
                        "category": category,
                        "confidence_score": round(float(abs(z)), 4),
                        "z_score": round(float(z), 4),
                        "rolling_mean": round(mean_val, 4),
                        "rolling_std": round(std_val, 4),
                        "actual_value": round(value, 4),
                        "detected_at": datetime.now(timezone.utc),
                    }
                )

                logger.warning(
                    "Anomaly detected",
                    extra={
                        "sensor_id": sensor_id,
                        "metric": metric,
                        "category": category,
                        "actual_value": round(value, 4),
                        "rolling_mean": round(mean_val, 4),
                        "rolling_std": round(std_val, 4),
                        "z_score": round(float(z), 4),
                        "std_deviations": round(float(abs(z)), 4),
                        "reading_id": row_id,
                    },
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

    categories = {}
    for r in anomaly_rows:
        categories[r["category"]] = categories.get(r["category"], 0) + 1
    logger.info(
        "Detected %d anomalies in %d readings",
        len(anomaly_rows),
        len(new_id_set),
        extra={"categories": categories},
    )
    return len(anomaly_rows)
