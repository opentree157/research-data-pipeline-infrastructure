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
- **Background anomaly detection**: CSV upload returns immediately after ingestion; anomaly detection runs as a `BackgroundTask` so the user isn't blocked.
- **Rolling-window z-score detection**: the anomaly detector computes per-sensor, per-metric rolling mean/std (window=20) and flags readings >2 standard deviations away. Confidence score = |z-score|.
- **Alembic migrations**: schema changes are tracked and applied automatically on startup, instead of `create_all()`.
- **nginx as reverse proxy**: single entry point, serves static files directly, strips `/api/` prefix and forwards to FastAPI. `root_path` ensures OpenAPI docs work correctly through the proxy.
- **Docker Compose with named volumes**: `pgdata` volume persists database across container restarts.
- **All config via environment variables**: `.env.example` documents every setting; nothing is hardcoded.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.9+ (for data generation and local testing)

### 1. Start the stack

```bash
cp .env.example .env    # customize if needed
docker compose up -d --build
```

The dashboard will be available at **http://localhost:8080**.

### 2. Generate test data

```bash
python3 2_generate_data.py -n 10000 -o sample_data.csv --seed 42
```

### 3. Ingest data

**Option A** - via the web dashboard: click "Upload CSV" and select `sample_data.csv`.

**Option B** - via curl:

```bash
curl -X POST http://localhost:8080/api/ingest \
  -F "file=@sample_data.csv"
```

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

| Method | Endpoint          | Description                                | Query Params                                    |
|--------|-------------------|--------------------------------------------|-------------------------------------------------|
| GET    | `/api/health`     | Health check with DB status and counts     | -                                               |
| POST   | `/api/ingest`     | Upload CSV file; detection runs in background | `file` (multipart)                              |
| GET    | `/api/anomalies`  | Query anomalies with filters               | `start`, `end`, `sensor_id`, `limit`, `offset`  |
| GET    | `/api/sensors`    | List distinct sensor IDs                   | -                                               |
| GET    | `/api/readings`   | Query raw sensor readings                  | `sensor_id`, `limit`, `offset`                  |

Interactive API docs are available at **http://localhost:8080/api/docs** when the stack is running.

## Running Tests

```bash
pip install -r api/requirements.txt -r tests/requirements-test.txt
pytest tests/ -v
```

Tests use SQLite by default so no database setup is required.

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push and PR to `main`:

1. **Test** - runs the test suite against both SQLite and a PostgreSQL service container
2. **Build** - builds the API Docker image and pushes to GitHub Container Registry (on merge to main)
3. **Deploy** - placeholder step that validates `docker-compose.yml` and documents deployment steps

To enable container registry pushes, the repository needs `packages: write` permission (enabled by default for GHCR).

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
│   ├── ingest.py           # CSV parsing and batch ingestion
│   └── anomaly_detector.py # Rolling z-score anomaly detection
├── frontend/
│   └── index.html          # Dashboard (anomaly table + filters + upload)
├── nginx/
│   └── nginx.conf          # Reverse proxy configuration
├── tests/
│   ├── conftest.py         # Fixtures (SQLite test DB, FastAPI client)
│   ├── test_api.py         # API endpoint tests
│   └── test_anomaly_detector.py  # Detection algorithm tests
├── .github/workflows/
│   └── ci.yml              # CI/CD pipeline
├── docker-compose.yml      # Local orchestration
├── .env.example            # Environment variable template
├── 2_generate_data.py      # Test data generator (provided)
├── 3_anomaly_detector.py   # Reference detector (provided)
└── DATA_GENERATOR_GUIDE.md # Data generator docs (provided)
```

## Cloud Deployment

The stack is designed for straightforward cloud deployment:

1. **Container registry**: CI pushes images to GHCR. Swap for ECR/GCR/ACR as needed.
2. **Database**: Replace the `db` service with a managed PostgreSQL instance (RDS, Cloud SQL, etc.) by updating `DATABASE_URL`.
3. **Compute**: Deploy containers to ECS/Fargate, Cloud Run, or a VM with Docker Compose.
4. **DNS/TLS**: Point a domain at nginx and add TLS termination (certbot, ALB, or cloud load balancer).

Environment variables make every component configurable without code changes.
