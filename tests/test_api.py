SAMPLE_CSV = """id,timestamp,sensor_id,temperature,humidity,pressure,location
1,2024-01-01T00:00:00Z,TEMP_001,22.5,45.2,1013.25,lab_a
2,2024-01-01T00:05:00Z,TEMP_001,22.7,45.8,1013.20,lab_a
3,2024-01-01T00:10:00Z,TEMP_001,22.3,45.5,1013.18,lab_a
4,2024-01-01T00:15:00Z,TEMP_001,22.6,45.1,1013.22,lab_a
5,2024-01-01T00:20:00Z,TEMP_001,22.8,44.9,1013.30,lab_a
6,2024-01-01T00:25:00Z,TEMP_001,22.4,45.3,1013.15,lab_a
7,2024-01-01T00:30:00Z,TEMP_001,22.9,45.7,1013.28,lab_a
8,2024-01-01T00:35:00Z,TEMP_001,22.1,45.0,1013.10,lab_a
9,2024-01-01T00:40:00Z,TEMP_001,22.5,45.4,1013.20,lab_a
10,2024-01-01T00:45:00Z,TEMP_001,22.7,45.6,1013.25,lab_a
11,2024-01-01T00:50:00Z,TEMP_001,45.0,45.2,1013.22,lab_a
"""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_ingest_csv(client):
    r = client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    assert r.status_code == 200
    data = r.json()
    assert data["readings_ingested"] == 11
    assert "job_id" in data


def test_get_anomalies_empty(client):
    r = client.get("/anomalies")
    assert r.status_code == 200
    assert r.json() == []


def test_ingest_then_query_anomalies(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/anomalies")
    assert r.status_code == 200
    anomalies = r.json()
    assert len(anomalies) >= 1
    assert anomalies[0]["reading"]["sensor_id"] == "TEMP_001"


def test_filter_by_sensor_id(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/anomalies", params={"sensor_id": "NONEXISTENT"})
    assert r.status_code == 200
    assert r.json() == []


def test_filter_by_date_range(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/anomalies", params={
        "start": "2024-01-01T00:40:00Z",
        "end": "2024-01-01T01:00:00Z",
    })
    assert r.status_code == 200
    anomalies = r.json()
    assert all(a["reading"]["sensor_id"] == "TEMP_001" for a in anomalies)


def test_filter_by_date_range_excludes(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/anomalies", params={
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-01-02T00:00:00Z",
    })
    assert r.status_code == 200
    assert r.json() == []


def test_sensors_list(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/sensors")
    assert r.status_code == 200
    assert "TEMP_001" in r.json()


def test_readings_endpoint(client):
    client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    r = client.get("/readings", params={"sensor_id": "TEMP_001", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 5
    assert all(d["sensor_id"] == "TEMP_001" for d in data)


# --- Job status tests ---

def test_job_status_after_ingest(client):
    r = client.post("/ingest", files={"file": ("data.csv", SAMPLE_CSV, "text/csv")})
    job_id = r.json()["job_id"]
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "completed"
    assert job["anomalies_found"] >= 1
    assert job["readings_count"] == 11


def test_job_not_found(client):
    r = client.get("/jobs/99999")
    assert r.status_code == 404


# --- Validation / error tests ---

def test_ingest_missing_columns(client):
    bad_csv = "timestamp,sensor_id\n2024-01-01T00:00:00Z,S1\n"
    r = client.post("/ingest", files={"file": ("bad.csv", bad_csv, "text/csv")})
    assert r.status_code == 400
    assert "Missing required columns" in r.json()["detail"]


def test_ingest_bad_timestamp(client):
    bad_csv = "id,timestamp,sensor_id,temperature,humidity,pressure,location\n1,not-a-date,S1,22.0,45.0,1013.0,lab\n"
    r = client.post("/ingest", files={"file": ("bad.csv", bad_csv, "text/csv")})
    assert r.status_code == 400
    assert "row 2" in r.json()["detail"]


def test_ingest_bad_numeric(client):
    bad_csv = "id,timestamp,sensor_id,temperature,humidity,pressure,location\n1,2024-01-01T00:00:00Z,S1,abc,45.0,1013.0,lab\n"
    r = client.post("/ingest", files={"file": ("bad.csv", bad_csv, "text/csv")})
    assert r.status_code == 400
    assert "row 2" in r.json()["detail"]


def test_ingest_empty_file(client):
    r = client.post("/ingest", files={"file": ("empty.csv", "", "text/csv")})
    assert r.status_code == 400


def test_ingest_headers_only(client):
    headers_only = "id,timestamp,sensor_id,temperature,humidity,pressure,location\n"
    r = client.post("/ingest", files={"file": ("h.csv", headers_only, "text/csv")})
    assert r.status_code == 400
    assert "no data rows" in r.json()["detail"]
