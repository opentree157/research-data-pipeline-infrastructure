# Research Data Pipeline Infrastructure

A scalable research data processing pipeline that ingests sensor data, detects anomalies using rolling-window statistics, and serves results via a REST API with a web dashboard.

## Architecture

```
┌─────────────┐       ┌───────────────┐       ┌────────────────┐
│   Browser    │──────▶│  nginx :8080  │──────▶│  FastAPI :8000 │
│  (frontend)  │◀──────│ reverse proxy │◀──────│   (api)        │
└─────────────┘       └───────────────┘       └───────┬────────┘
                                                      │
                                              ┌───────▼────────┐
                                              │ PostgreSQL :5432│
                                              │   (sensor_data) │
                                              └────────────────┘
```

**Components:**

| Service    | Role                                                             | Tech                  |
|------------|------------------------------------------------------------------|-----------------------|
| **api**    | CSV ingestion, anomaly detection, REST endpoints                 | FastAPI, SQLAlchemy   |
| **db**     | Persistent storage for readings and anomaly results              | PostgreSQL 16         |
| **nginx**  | Reverse proxy, serves static frontend, routes `/api/*` to API   | nginx 1.27            |
| **frontend** | Single-page dashboard showing anomaly table with filters       | Vanilla HTML/JS       |

### Design Decisions

- **FastAPI** over Flask: automatic OpenAPI docs, async support, Pydantic validation, and dependency injection for DB sessions.
- **SQLAlchemy Core `insert().returning()`**: true batch inserts with ID retrieval in a single roundtrip, efficient for >10k records.
- **Background anomaly detection**: CSV upload returns immediately after ingestion; anomaly detection runs as a `BackgroundTask`. This means the ingest response reports `processing: true` with `anomalies_detected: 0` — anomalies appear after a short delay.
- **Rolling-window z-score detection with historical context**: the anomaly detector fetches the prior `ROLLING_WINDOW_SIZE` (default 20) readings per sensor from the database before processing a new batch. This ensures rolling statistics are correct across ingest boundaries. Only newly ingested readings are evaluated for anomalies. Confidence score = |z-score|.
- **Idempotent anomaly writes**: a unique constraint on `(sensor_data_id, anomaly_type)` prevents duplicate anomaly records if detection runs more than once on the same data. PostgreSQL uses `ON CONFLICT DO NOTHING`; SQLite falls back to a check-before-insert pattern.
- **Alembic migrations**: schema changes are tracked and applied automatically on startup, instead of `create_all()`.
- **nginx as reverse proxy**: single entry point, serves static files directly, strips `/api/` prefix and forwards to FastAPI. `root_path` ensures OpenAPI docs work correctly through the proxy at `/api/docs`.
- **Docker Compose with named volumes**: `pgdata` volume persists database across container restarts.
- **All config via environment variables**: `docker-compose.yml` uses `${VAR:-default}` syntax for every setting. `root_path` and CORS origins are also configurable.

### Operational Notes

- **Processing latency**: after CSV upload, anomaly detection runs in a background thread. For 10k rows, this typically takes 1-2 seconds. The frontend waits 2 seconds after upload before refreshing anomaly data.
- **Memory**: the current design reads the full CSV and all affected readings into memory. This handles tens of thousands of rows comfortably but would need streaming for millions.
- **Test safety**: the test suite refuses to run against any PostgreSQL database whose name does not contain "test". This prevents accidental data loss when `DATABASE_URL` points to a real database.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.9+ (for data generation and local testing)

### 1. Start the stack

```bash
docker compose up -d --build
```

All configuration has sensible defaults in `docker-compose.yml`. No `.env` file is required for local development.

The dashboard will be available at **http://localhost:8080**.

### 2. Generate test data

```bash
python3 2_generate_data.py -n 10000 -o sample_data.csv --seed 42
```

### 3. Ingest data

**Option A** — via the web dashboard: click "Upload CSV" and select `sample_data.csv`.

**Option B** — via curl:

```bash
curl -X POST http://localhost:8080/api/ingest \
  -F "file=@sample_data.csv"
```

The response returns immediately with the number of ingested readings. Anomaly detection runs in the background.

### 4. Query anomalies

```bash
# All anomalies (paginated)
curl "http://localhost:8080/api/anomalies?limit=10"

# Filter by sensor and date range
curl "http://localhost:8080/api/anomalies?sensor_id=TEMP_001&start=2024-01-01T00:00:00Z&end=2024-01-02T00:00:00Z"

# List sensors
curl http://localhost:8080/api/sensors

# Health check
curl http://localhost:8080/api/health
```

### 5. Stop the stack

```bash
docker compose down        # stop containers, keep data
docker compose down -v     # stop containers and delete data
```

## API Reference

| Method | Endpoint          | Description                                      | Query Params                                    |
|--------|-------------------|--------------------------------------------------|-------------------------------------------------|
| GET    | `/api/health`     | Health check with DB status and counts            | -                                               |
| POST   | `/api/ingest`     | Upload CSV; returns `job_id` for status tracking  | `file` (multipart)                              |
| GET    | `/api/jobs/{id}`  | Poll processing job status                        | -                                               |
| GET    | `/api/anomalies`  | Query anomalies with filters                      | `start`, `end`, `sensor_id`, `limit`, `offset`  |
| GET    | `/api/sensors`    | List distinct sensor IDs                          | -                                               |
| GET    | `/api/readings`   | Query raw sensor readings                         | `sensor_id`, `limit`, `offset`                  |

Interactive API docs (Swagger UI) are available at **http://localhost:8080/api/docs** when the stack is running.

**Validation**: The ingest endpoint validates CSV structure (required columns, timestamp format, numeric fields) and returns `400` with a descriptive error for malformed input. The health endpoint returns `status: "degraded"` when the database is unreachable, instead of failing with a 500.

**Processing jobs**: `POST /api/ingest` returns a `job_id`. Poll `GET /api/jobs/{id}` to check status (`pending`, `completed`, `failed`). On completion, `anomalies_found` contains the count. On failure, `error` contains the traceback. The frontend polls automatically and shows the result.

## Running Tests

```bash
pip install -r api/requirements.txt -r tests/requirements-test.txt
pytest tests/ -v
```

Tests use SQLite by default. To run against PostgreSQL:

```bash
DATABASE_URL=postgresql://pipeline:pipeline@localhost:5432/sensor_data_test \
  pytest tests/ -v
```

The test suite will refuse to run if `DATABASE_URL` points to a PostgreSQL database whose name does not contain "test".

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push and PR to `main`:

| Job       | Trigger               | What it does                                                        |
|-----------|-----------------------|---------------------------------------------------------------------|
| **test**  | Every push and PR     | Runs test suite against SQLite and a PostgreSQL service container    |
| **build** | Every push and PR     | Builds API and nginx Docker images; pushes to GHCR on merge to main |
| **deploy**| Merge to main only    | SSHs into the production host, pulls new images, restarts services  |

**Deploy is gated on configuration.** It only runs when `DEPLOY_HOST` is set as a repository variable. To enable it:

1. Create a GitHub environment named `production`
2. Set repository variables: `DEPLOY_HOST`, `DEPLOY_USER`
3. Set repository secret: `DEPLOY_SSH_KEY`
4. Ensure the target host has Docker installed and `/opt/pipeline/` created

Without these, the test and build jobs run normally and the deploy job is skipped.

## Project Structure

```
├── api/
│   ├── Dockerfile          # API container image
│   ├── .dockerignore       # Excludes test/dev files from image
│   ├── requirements.txt    # Python dependencies
│   ├── alembic.ini         # Alembic configuration
│   ├── migrations/         # Database migration scripts
│   ├── main.py             # FastAPI application and routes
│   ├── config.py           # Environment variable configuration
│   ├── database.py         # SQLAlchemy engine and session
│   ├── models.py           # ORM models (SensorReading, Anomaly)
│   ├── schemas.py          # Pydantic request/response schemas
│   ├── ingest.py           # CSV parsing, validation, and batch ingestion
│   └── anomaly_detector.py # Rolling z-score anomaly detection with historical context
├── frontend/
│   └── index.html          # Dashboard (anomaly table + filters + upload)
├── nginx/
│   ├── Dockerfile          # Production nginx image with baked-in frontend
│   └── nginx.conf          # Reverse proxy configuration
├── tests/
│   ├── conftest.py         # Fixtures, DB safety guard, SQLite/PG support
│   ├── test_api.py         # API endpoint + validation tests
│   └── test_anomaly_detector.py  # Detection, historical context, idempotency tests
├── .github/workflows/
│   └── ci.yml              # CI/CD pipeline (test → build → deploy)
├── docker-compose.yml      # Local development orchestration (bind mounts)
├── docker-compose.prod.yml # Production orchestration (built images)
├── 2_generate_data.py      # Test data generator (provided)
├── 3_anomaly_detector.py   # Reference detector (provided)
└── DATA_GENERATOR_GUIDE.md # Data generator docs (provided)
```

## Cloud Deployment

**Local dev** uses `docker-compose.yml` with bind mounts for nginx config and frontend HTML, allowing live editing.

**Production** uses `docker-compose.prod.yml` which references pushed images from GHCR. The nginx service builds a self-contained image with frontend and config baked in — no bind mounts required.

To deploy manually:

```bash
# On the target host
export API_IMAGE=ghcr.io/your-org/research-data-pipeline/api:latest
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

To use a managed database instead of the containerized one, set `DATABASE_URL` and remove the `db` service from the compose file.

### Environment Variables

| Variable             | Default                | Description                          |
|----------------------|------------------------|--------------------------------------|
| `POSTGRES_USER`      | `pipeline`             | PostgreSQL username                  |
| `POSTGRES_PASSWORD`  | `pipeline`             | PostgreSQL password                  |
| `POSTGRES_DB`        | `sensor_data`          | PostgreSQL database name             |
| `DB_PORT`            | `5432`                 | Exposed PostgreSQL port              |
| `APP_PORT`           | `8080`                 | Exposed HTTP port                    |
| `ROLLING_WINDOW_SIZE`| `20`                   | Rolling window for anomaly detection |
| `ANOMALY_THRESHOLD`  | `2.0`                  | Z-score threshold for anomalies      |
| `API_ROOT_PATH`      | `/api`                 | FastAPI root path (for reverse proxy)|
| `ALLOWED_ORIGINS`    | `*`                    | CORS allowed origins (comma-separated)|
