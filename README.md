# Research Data Pipeline Infrastructure

A scalable research data processing pipeline that ingests sensor data, detects anomalies using rolling-window statistics, and serves results via a REST API with a web dashboard.

## Architecture

```
┌─────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   Browser   │──────▶│    nginx :8080   │──────▶│   FastAPI :8000  │
│  (frontend) │◀──────│  (reverse proxy) │◀──────│       (api)      │
└─────────────┘       └──────────────────┘       └───────┬──────────┘
                                                         │
                                                 ┌───────▼──────────┐
                                                 │ PostgreSQL :5432 │
                                                 │   (sensor_data)  │
                                                 └────────┬─────────┘
                                                          │
┌───────────────────── Observability ─────────────────────┤
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┤
│  │ Grafana :3000│◀───│  Prometheus  │◀───│   Exporters  │
│  │ (dashboards) │    │    :9090     │    │ (pg, nginx)  │
│  │              │◀───│              │    └──────────────┘
│  │              │    └──────────────┘
│  │              │◀───┌──────────────┐    ┌───────────────┐
│  │              │    │  Loki :3100  │◀───│   Promtail    │
│  └──────────────┘    │    (logs)    │    │ (Docker logs) │
│                      └──────────────┘    └───────────────┘
└─────────────────────────────────────────────────────────┘
```

**Components:**

| Service    | Role                                                             | Tech                  |
|------------|------------------------------------------------------------------|-----------------------|
| **api**    | CSV ingestion, anomaly detection, REST endpoints                 | FastAPI, SQLAlchemy   |
| **db**     | Persistent storage for readings and anomaly results              | PostgreSQL 16         |
| **nginx**  | Reverse proxy, serves static frontend, routes `/api/*` to API   | nginx 1.27            |
| **frontend** | Single-page dashboard showing anomaly table with filters       | Vanilla HTML/JS       |
| **prometheus** | Metrics collection and alert evaluation                      | Prometheus            |
| **grafana** | Dashboards, log viewer, alert visualization                     | Grafana               |
| **loki**   | Log aggregation from all containers                              | Loki                  |

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

- **Dashboard**: http://localhost:8080
- **Grafana** (monitoring): http://localhost:3000 (admin / admin)
- **API docs**: http://localhost:8080/api/docs

### 2. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r api/requirements.txt -r tests/requirements-test.txt
```

### 3. Generate test data

```bash
python3 2_generate_data.py -n 10000 -o sample_data.csv --seed 42
```

### 4. Ingest data

**Option A** — via the web dashboard: click "Upload CSV" and select `sample_data.csv`.

**Option B** — via curl:

```bash
curl -X POST http://localhost:8080/api/ingest \
  -F "file=@sample_data.csv"
```

The response returns immediately with the number of ingested readings. Anomaly detection runs in the background.

### 5. Query anomalies

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

### 6. Stop the stack

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

| Job       | PR opened/updated               | PR merged to main                                     |
|-----------|----------------------------------|-------------------------------------------------------|
| **test**  | Runs unit + integration tests    | Runs unit + integration tests                         |
| **build** | Builds images (validates Docker) | Builds and pushes images to GHCR                      |
| **deploy**| Skipped                          | SSHs into production host, pulls images, restarts     |

On a PR, the build job validates that the Dockerfiles compile but does not push images. On merge to main, it pushes SHA-tagged and `latest` images to GHCR and then deploys.

**Deploy is gated on configuration.** It only runs when `DEPLOY_HOST` is set as a repository variable. To enable it:

1. Create a GitHub environment named `production`
2. Set repository variables: `DEPLOY_HOST`, `DEPLOY_USER`
3. Set repository secrets: `DEPLOY_SSH_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
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
├── terraform/
│   ├── main.tf             # EC2 instance, security group, Elastic IP
│   ├── variables.tf        # Configurable inputs (region, instance type, images, creds)
│   ├── outputs.tf          # Public IP, dashboard URL, SSH command
│   ├── cloud-init.yml      # Bootstraps Docker and starts the stack on first boot
│   └── terraform.tfvars.example
├── monitoring/
│   ├── prometheus/
│   │   ├── prometheus.yml  # Scrape config (API, PostgreSQL, nginx)
│   │   └── alerts.yml      # Alert rules (error rate, latency, downtime)
│   ├── grafana/
│   │   ├── provisioning/   # Auto-configured datasources (Prometheus, Loki)
│   │   └── dashboards/     # Pre-built Pipeline Overview dashboard
│   ├── loki/
│   │   └── loki-config.yml # Log aggregation config (7-day retention)
│   └── promtail/
│       └── promtail-config.yml  # Docker log collection via socket
├── .github/workflows/
│   └── ci.yml              # CI/CD pipeline (test → build → deploy)
├── docker-compose.yml      # Local development orchestration (bind mounts)
├── docker-compose.prod.yml # Production orchestration (built images)
├── 2_generate_data.py      # Test data generator (provided)
├── 3_anomaly_detector.py   # Reference detector (provided)
└── DATA_GENERATOR_GUIDE.md # Data generator docs (provided)
```

## Observability

The stack includes full observability out of the box: metrics, logs, and alerting — all self-hosted, no external accounts needed.

### Components

| Service               | Role                                          | Port  |
|-----------------------|-----------------------------------------------|-------|
| **Prometheus**        | Scrapes metrics from API, PostgreSQL, nginx   | 9090  |
| **Grafana**           | Dashboards and alert visualization            | 3000  |
| **Loki**              | Log aggregation from all containers           | 3100  |
| **Promtail**          | Ships Docker container logs to Loki           | -     |
| **postgres-exporter** | Exposes PostgreSQL metrics to Prometheus       | -     |
| **nginx-exporter**    | Exposes nginx metrics to Prometheus            | -     |

### Dashboards

Grafana is available at **http://localhost:3000** (default login: `admin` / `admin`).

A **Pipeline Overview** dashboard is pre-provisioned with:
- Request rate and error rate (5xx) over time
- Latency percentiles (p50 / p95 / p99)
- Requests in progress
- PostgreSQL connection count and row estimates
- Response status code distribution
- Request rate by endpoint
- Live application logs (via Loki)

### Alerts

Prometheus alert rules fire on:
- **HighErrorRate** — >5% of requests returning 5xx for 2 minutes
- **HighLatency** — p95 latency above 2s for 5 minutes
- **APIDown** — FastAPI metrics endpoint unreachable for 1 minute
- **PostgreSQLDown** — PostgreSQL exporter unreachable for 1 minute
- **HighDatabaseConnections** — >80 active connections for 5 minutes
- **NginxDown** — nginx exporter unreachable for 1 minute

Alerts appear in Grafana's Alerting UI. To receive notifications (email, Slack, PagerDuty), configure a contact point in Grafana under Alerting > Contact points.

### Structured Logging

The API emits JSON-structured logs with `timestamp`, `level`, `name`, and `message` fields. Key events logged:
- CSV ingestion (readings count, job ID)
- Anomaly detection completion (job ID, anomalies found)
- Anomaly detection failures (with traceback)

Logs from all containers are collected by Promtail and queryable in Grafana via the Loki datasource.

## Cloud Deployment (AWS)

The `terraform/` directory contains a Terraform config that provisions the full stack on AWS:

- EC2 instance (Amazon Linux 2023) with Docker pre-installed via cloud-init
- Security group allowing HTTP (80) and SSH (configurable CIDR)
- Elastic IP for a stable public address
- Automatic stack startup on first boot

### Deploy

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

terraform init
terraform plan
terraform apply
```

After a few minutes, `terraform output url` gives you the dashboard URL.

### Tear down

```bash
terraform destroy
```

### Manual deployment (without Terraform)

Provision any VM with Docker installed, then:

```bash
scp docker-compose.prod.yml user@host:/opt/pipeline/docker-compose.yml

ssh user@host "cd /opt/pipeline && \
  export API_IMAGE=ghcr.io/you/repo/api:latest && \
  export NGINX_IMAGE=ghcr.io/you/repo/nginx:latest && \
  export POSTGRES_USER=pipeline && \
  export POSTGRES_PASSWORD=changeme && \
  docker compose up -d"
```

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
| `PROMETHEUS_PORT`    | `9090`                 | Exposed Prometheus port              |
| `GRAFANA_PORT`       | `3000`                 | Exposed Grafana port                 |
| `GRAFANA_USER`       | `admin`                | Grafana admin username               |
| `GRAFANA_PASSWORD`   | `admin`                | Grafana admin password               |
