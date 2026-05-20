from datetime import datetime, timezone

from models import SensorReading
from anomaly_detector import detect_anomalies


def _make_readings(db, temps, sensor_id="TEST_001", start_minute=0):
    readings = []
    for i, t in enumerate(temps):
        r = SensorReading(
            timestamp=datetime(2024, 1, 1, 0, start_minute + i, tzinfo=timezone.utc),
            sensor_id=sensor_id,
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


def test_historical_context_across_ingests(db):
    """Anomaly detection should use prior readings from DB for rolling stats."""
    history_ids = _make_readings(db, [22.0] * 25, start_minute=0)
    detect_anomalies(db, history_ids)

    spike_ids = _make_readings(db, [50.0], start_minute=25)
    count = detect_anomalies(db, spike_ids)
    assert count >= 1


def test_idempotent_detection(db):
    """Running detection twice on the same readings should not create duplicates."""
    temps = [22.0] * 25 + [50.0]
    ids = _make_readings(db, temps)

    count1 = detect_anomalies(db, ids)
    count2 = detect_anomalies(db, ids)

    assert count1 >= 1
    assert count2 >= 1

    from models import Anomaly
    total = db.query(Anomaly).count()
    assert total == count1
