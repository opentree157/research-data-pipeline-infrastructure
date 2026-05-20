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
REQUIRED_COLUMNS = {"timestamp", "sensor_id", "temperature", "humidity", "pressure", "location"}


class ValidationError(Exception):
    pass


def parse_timestamp(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _validate_and_parse(file_content: str) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(file_content))
        if reader.fieldnames is None:
            raise ValidationError("Empty or unreadable CSV file")
    except csv.Error as e:
        raise ValidationError(f"Invalid CSV format: {e}")

    headers = set(reader.fieldnames)
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValidationError(
            f"Missing required columns: {', '.join(sorted(missing))}"
        )

    rows = []
    errors = []
    for i, raw in enumerate(reader, start=2):
        row_num = i
        try:
            ts = raw.get("timestamp", "").strip()
            if not ts:
                raise ValueError("empty timestamp")
            parsed_ts = parse_timestamp(ts)

            temp = float(raw["temperature"])
            humid = float(raw["humidity"])
            press = float(raw["pressure"])

            sid = raw.get("sensor_id", "").strip()
            loc = raw.get("location", "").strip()
            if not sid:
                raise ValueError("empty sensor_id")
            if not loc:
                raise ValueError("empty location")

            rows.append({
                "timestamp": parsed_ts,
                "sensor_id": sid,
                "temperature": temp,
                "humidity": humid,
                "pressure": press,
                "location": loc,
            })
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"row {row_num}: {e}")
            if len(errors) >= 10:
                break

    if errors:
        raise ValidationError(
            f"Validation failed on {len(errors)} row(s): {'; '.join(errors)}"
        )

    if not rows:
        raise ValidationError("CSV file contains no data rows")

    return rows


def ingest_csv(db: Session, file_content: str) -> list[int]:
    rows = _validate_and_parse(file_content)

    all_ids: list[int] = []
    stmt = insert(SensorReading).returning(SensorReading.id)

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        result = db.execute(stmt, batch)
        all_ids.extend(row[0] for row in result)

    db.commit()
    logger.info("Ingested %d readings", len(all_ids))
    return all_ids
