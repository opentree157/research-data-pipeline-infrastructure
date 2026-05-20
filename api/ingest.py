"""CSV ingestion into PostgreSQL."""

import csv
import io
import logging
from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.orm import Session

from models import SensorReading

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


def parse_timestamp(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _parse_rows(file_content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(file_content))
    return [
        {
            "timestamp": parse_timestamp(row["timestamp"]),
            "sensor_id": row["sensor_id"],
            "temperature": float(row["temperature"]),
            "humidity": float(row["humidity"]),
            "pressure": float(row["pressure"]),
            "location": row["location"],
        }
        for row in reader
    ]


def ingest_csv(db: Session, file_content: str) -> list[int]:
    rows = _parse_rows(file_content)
    if not rows:
        return []

    all_ids: list[int] = []
    stmt = insert(SensorReading).returning(SensorReading.id)

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        result = db.execute(stmt, batch)
        all_ids.extend(row[0] for row in result)

    db.commit()
    logger.info("Ingested %d readings", len(all_ids))
    return all_ids
