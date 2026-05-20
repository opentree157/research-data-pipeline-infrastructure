from datetime import datetime, timezone

from models import SensorReading
from anomaly_detector import detect_anomalies


def _make_readings(db, temps):
    readings = []
    for i, t in enumerate(temps):
        r = SensorReading(
            timestamp=datetime(2024, 1, 1, 0, i, tzinfo=timezone.utc),
            sensor_id="TEST_001",
            temperature=t,
            humidity=45.0,
            pressure=1013.0,
            location="test",
        )
        readings.append(r)
    db.bulk_save_objects(readings, return_defaults=True)
    db.commit()
    return [r.id for r in readings]


def test_no_anomalies_in_stable_data(db):
    ids = _make_readings(db, [22.0 + 0.1 * i % 0.5 for i in range(30)])
    count = detect_anomalies(db, ids)
    assert count == 0


def test_detects_spike(db):
    temps = [22.0] * 25 + [50.0]
    ids = _make_readings(db, temps)
    count = detect_anomalies(db, ids)
    assert count >= 1


def test_empty_input(db):
    count = detect_anomalies(db, [])
    assert count == 0
