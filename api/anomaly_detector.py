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
from metrics import anomalies_detected_total
from models import Anomaly, SensorReading

logger = logging.getLogger(__name__)

METRICS = ["temperature", "humidity", "pressure"]

SENSOR_FAILURE_VALUES = {-999.0, 0.0}
SPIKE_Z_THRESHOLD = 5.0
DRIFT_WINDOW = 5


def _fetch_with_history(
    db: Session, reading_ids: List[int]
) -> tuple[pd.DataFrame, set[int]]:
    if not reading_ids:
        return pd.DataFrame(), set()

    min_id = min(reading_ids)
    max_id = max(reading_ids)
    new_id_set = set(reading_ids)

    new_readings = (
        db.query(SensorReading)
        .filter(SensorReading.id.between(min_id, max_id))
        .all()
    )
    new_readings = [r for r in new_readings if r.id in new_id_set]

    if not new_readings:
        return pd.DataFrame(), set()

    earliest_by_sensor = {}
    for r in new_readings:
        if r.sensor_id not in earliest_by_sensor or r.timestamp < earliest_by_sensor[r.sensor_id]:
            earliest_by_sensor[r.sensor_id] = r.timestamp

    history = []
    for sid, earliest in earliest_by_sensor.items():
        prior = (
            db.query(SensorReading)
            .filter(
                and_(
                    SensorReading.sensor_id == sid,
                    SensorReading.timestamp < earliest,
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
    now = datetime.now(timezone.utc)

    for sensor_id, sensor_df in df.groupby("sensor_id"):
        sensor_df = sensor_df.reset_index(drop=True)
        is_new = sensor_df["id"].isin(new_id_set)

        stats = {}
        for metric in METRICS:
            rm = sensor_df[metric].rolling(window=ROLLING_WINDOW_SIZE, min_periods=1).mean()
            rs = sensor_df[metric].rolling(window=ROLLING_WINDOW_SIZE, min_periods=1).std()
            z = (sensor_df[metric] - rm) / rs

            diffs = sensor_df[metric].diff()
            drift_up = diffs.rolling(window=DRIFT_WINDOW, min_periods=DRIFT_WINDOW - 1).min() > 0
            drift_down = diffs.rolling(window=DRIFT_WINDOW, min_periods=DRIFT_WINDOW - 1).max() < 0

            stats[metric] = {
                "mean": rm,
                "std": rs,
                "z": z,
                "is_drift": drift_up | drift_down,
            }

        for metric in METRICS:
            z_scores = stats[metric]["z"]
            anomaly_mask = is_new & z_scores.notna() & (z_scores.abs() > ANOMALY_THRESHOLD)
            anomaly_indices = sensor_df.index[anomaly_mask]

            if anomaly_indices.empty:
                continue

            for idx in anomaly_indices:
                value = float(sensor_df.loc[idx, metric])
                z = float(z_scores.loc[idx])
                mean_val = float(stats[metric]["mean"].loc[idx])
                std_val = float(stats[metric]["std"].loc[idx])
                row_id = int(sensor_df.loc[idx, "id"])

                if value in SENSOR_FAILURE_VALUES:
                    category = "sensor_failure"
                elif abs(z) >= SPIKE_Z_THRESHOLD:
                    category = "spike"
                elif stats[metric]["is_drift"].loc[idx]:
                    category = "drift"
                else:
                    cross_anomalies = sum(
                        1 for m in METRICS
                        if m != metric
                        and sensor_df.loc[idx, m] not in SENSOR_FAILURE_VALUES
                        and pd.notna(stats[m]["z"].loc[idx])
                        and abs(stats[m]["z"].loc[idx]) > ANOMALY_THRESHOLD
                    )
                    category = "noise_burst" if cross_anomalies >= 1 else "spike"

                anomaly_rows.append({
                    "sensor_data_id": row_id,
                    "anomaly_type": f"{metric}_anomaly",
                    "category": category,
                    "confidence_score": round(abs(z), 4),
                    "z_score": round(z, 4),
                    "rolling_mean": round(mean_val, 4),
                    "rolling_std": round(std_val, 4),
                    "actual_value": round(value, 4),
                    "detected_at": now,
                })
                anomalies_detected_total.labels(
                    sensor_id=sensor_id, category=category, metric=metric,
                ).inc()

    if not anomaly_rows:
        logger.info("Detected 0 anomalies in %d readings", len(new_id_set))
        return 0

    categories = {}
    for r in anomaly_rows:
        categories[r["category"]] = categories.get(r["category"], 0) + 1
    logger.info(
        "Detected %d anomalies in %d readings",
        len(anomaly_rows),
        len(new_id_set),
        extra={"categories": categories},
    )

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

    return len(anomaly_rows)
