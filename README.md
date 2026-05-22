# Research Data Pipeline Infrastructure

A scalable research data processing pipeline that ingests sensor data, detects anomalies using rolling-window statistics, and serves results via a REST API with a web dashboard.

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

## How It Works

Everything runs as Docker containers orchestrated by Docker Compose. One command (`docker compose up`) starts the entire system.

**nginx** is the front door. It's the only thing exposed to the outside world (port 8080). When you visit the dashboard in your browser, nginx serves the static HTML directly. When the browser makes an API call to `/api/anything`, nginx strips the `/api/` prefix and forwards the request to the FastAPI backend.

**FastAPI** is the brain. It handles three things: ingesting CSV files, running anomaly detection, and answering queries. When you upload a CSV, it validates the data (correct columns, parseable timestamps, numeric values), batch-inserts the readings into PostgreSQL, and kicks off anomaly detection in a background thread. You get a response immediately with a job ID — no waiting around. The frontend polls that job ID until detection finishes.

**PostgreSQL** stores everything: raw sensor readings, detected anomalies, and processing job status. Data persists across container restarts via a Docker named volume. Schema changes are managed by Alembic migrations, which run automatically when the API starts up.

**The anomaly detector** looks at each sensor's readings in time order using a rolling window (default: 20 readings). For each metric (temperature, humidity, pressure), it computes the rolling mean and standard deviation. If a reading is more than 2 standard deviations from the mean, it's flagged as an anomaly with a confidence score (the absolute z-score) and classified into one of four categories: **spike** (extreme single-point deviation), **drift** (sustained monotonic trend), **sensor_failure** (sentinel values like -999 or 0), or **noise_burst** (multiple metrics anomalous simultaneously). It pulls historical readings from the database so the rolling window works correctly across multiple CSV uploads.

**The frontend** is a single HTML file with vanilla JavaScript. It shows anomalies in a sortable, filterable, paginated table with color-coded confidence levels. All rendering uses DOM node creation (not innerHTML) to prevent XSS from CSV-controlled fields.

**Monitoring** runs alongside the application. Prometheus scrapes metrics from the API (request rates, latency percentiles, error counts), PostgreSQL (connections, row counts), and nginx (active connections). Loki collects logs from every container. Grafana ties it all together with a pre-built dashboard and alert rules that fire on high error rates, high latency, or services going down.

```
┌─────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   Browser   │──────▶│    nginx :8080   │──────▶│   FastAPI :8000  │
│  (frontend) │◀──────│  (reverse proxy) │◀──────│       (api)      │
└─────────────┘       └──────────────────┘       └────────┬─────────┘
                                                          │
                                                 ┌────────▼─────────┐
                                                 │ PostgreSQL :5432 │
                                                 │   (sensor_data)  │
                                                 └────────┬─────────┘
                                                          │
┌──────────────────── Observability ──────────────────────┤
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │ Grafana :3000│◀───│  Prometheus  │◀───│  Exporters │ │
│  │ (dashboards) │    │    :9090     │    │ (pg, nginx)│ │
│  │              │◀───│              │    └────────────┘ │
│  │              │    └──────────────┘                   │
│  │              │◀───┌──────────────┐    ┌─────────────┐│
│  │              │    │  Loki :3100  │◀───│   Promtail  ││
│  └──────────────┘    │    (logs)    │    │(Docker logs)││
│                      └──────────────┘    └─────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Design Decisions

- **FastAPI over Flask** — automatic OpenAPI docs, async support, Pydantic validation, and dependency injection for DB sessions.
- **SQLAlchemy Core `insert().returning()`** — true batch inserts with ID retrieval in a single roundtrip, efficient for >10k records.
- **Background anomaly detection** — CSV upload returns immediately; detection runs as a BackgroundTask. A ProcessingJob record tracks status so the frontend can poll for completion.
- **Idempotent anomaly writes** — a unique constraint on `(sensor_data_id, anomaly_type)` prevents duplicate anomaly records. PostgreSQL uses `ON CONFLICT DO NOTHING`; SQLite falls back to check-before-insert.
- **Alembic migrations** — schema changes are tracked and applied automatically on startup, not via `create_all()`.
- **nginx path stripping** — the trailing slash in `proxy_pass http://api/` strips the `/api/` prefix. `root_path="/api"` keeps OpenAPI docs working through the proxy.
- **Named volumes** — `pgdata` persists the database across container restarts.
- **All config via environment variables** — `docker-compose.yml` uses `${VAR:-default}` for every setting. No `.env` file needed for local development.
- **Self-hosted observability** — Prometheus + Grafana + Loki runs alongside the app with no external accounts or API keys. Dashboards and datasources are auto-provisioned.

### Performance and Scaling

The current architecture handles **10k–100k row CSVs comfortably** in a single request with no infrastructure changes:

| Dataset Size | Ingest (sync) | Anomaly Detection (background) | Total |
|-------------|---------------|-------------------------------|-------|
| 10,000 rows  | < 1s          | ~1s                           | ~1–2s |
| 30,000 rows  | ~1s           | ~1–2s                         | ~2–3s |
| 100,000 rows | ~3s           | ~3–4s                         | ~6–7s |

**Why it's fast at this scale:**

- **Batch inserts** — `ingest_csv` uses SQLAlchemy Core `insert().returning()` to write rows in chunks of 5,000. At 100k rows that's 20 bulk INSERT round-trips, not 100k individual ones.
- **Vectorized detection** — anomaly detection pre-computes rolling mean, standard deviation, z-scores, and drift detection for all metrics per sensor using pandas vectorized operations. Classification uses pre-computed cross-metric stats instead of recalculating per anomaly.
- **Range queries** — the detector fetches new readings with `WHERE id BETWEEN min AND max` instead of a massive `IN (...)` clause, keeping SQL parse time constant regardless of batch size.
- **Immediate response** — the user gets a response with a `job_id` as soon as ingestion completes. Detection runs in a FastAPI `BackgroundTask`, and the frontend polls for completion.

**Where it would break down (500k+ rows, concurrent uploads):**

The current system processes one upload at a time in a single background thread inside the API process. This works because:
1. Uploads are sequential — one user uploading at a time.
2. The dataset fits in memory — 100k rows is ~50MB as a pandas DataFrame.
3. Detection finishes fast enough that the background thread is free before the next upload.

At higher scale, these assumptions fail:

- **Concurrent uploads** would queue up in a single background thread. Upload B's detection won't start until upload A's finishes. Under load, the queue grows unbounded.
- **Memory pressure** — multiple 500k-row DataFrames in the API process could exhaust container memory.
- **No retry semantics** — if the API process crashes mid-detection, the job stays "pending" forever. There's no dead-letter queue or automatic retry.

**Future optimization: Celery + Redis task queue**

The natural next step is to move anomaly detection out of the API process and into a dedicated worker pool:

```
Browser → nginx → FastAPI → Redis (task broker)
                                  ↓
                          Celery Workers (1..N)
                                  ↓
                            PostgreSQL
```

What changes:
- **Redis** acts as the message broker. `POST /ingest` enqueues a detection task instead of using `BackgroundTasks`.
- **Celery workers** run as separate containers, each pulling tasks from Redis. Scale horizontally by adding more worker replicas.
- **Retry and failure handling** comes built-in — failed tasks retry with exponential backoff, dead-letter after N attempts. No more silent "pending" jobs.
- **Concurrency** — multiple uploads process in parallel across workers instead of queuing in a single thread.

The change to the application code is small — replace `background_tasks.add_task(_run_detection, ...)` with `detect_anomalies_task.delay(job_id, reading_ids)` and add a `celery_app.py` config. The detection logic itself doesn't change.

This is worth doing when you're handling multiple concurrent users or uploads larger than 500k rows. For a single-user pipeline processing 10k–100k rows at a time, the current `BackgroundTask` approach is simpler and fast enough.

### Operational Notes

- **Memory** — the current design reads the full CSV into memory. Fine for hundreds of thousands of rows, but would need streaming for millions.
- **Test safety** — the test suite refuses to run against any PostgreSQL database whose name does not contain "test".

## API Reference

| Method | Endpoint            | Description                                      | Query Params                                                                          |
|--------|---------------------|--------------------------------------------------|---------------------------------------------------------------------------------------|
| GET    | `/api/health`       | Health check with DB status and counts            | -                                                                                     |
| POST   | `/api/ingest`       | Upload CSV; returns `job_id` for status tracking  | `file` (multipart)                                                                    |
| GET    | `/api/jobs/{id}`    | Poll processing job status                        | -                                                                                     |
| GET    | `/api/anomalies`    | Query anomalies with filters and sorting          | `start`, `end`, `sensor_id`, `location`, `anomaly_type`, `category`, `sort_by`, `sort_dir`, `limit`, `offset` |
| GET    | `/api/sensors`      | List distinct sensor IDs                          | -                                                                                     |
| GET    | `/api/locations`    | List distinct sensor locations                    | -                                                                                     |
| GET    | `/api/anomaly-types`| List distinct anomaly types (metrics)             | -                                                                                     |
| GET    | `/api/categories`   | List distinct anomaly categories                  | -                                                                                     |
| GET    | `/api/readings`     | Query raw sensor readings                         | `sensor_id`, `limit`, `offset`                                                        |

Interactive API docs (Swagger UI) are available at **http://localhost:8080/api/docs** when the stack is running.

**Validation**: The ingest endpoint validates CSV structure (required columns, timestamp format, numeric fields) and returns `400` with a descriptive error for malformed input. The health endpoint returns `status: "degraded"` when the database is unreachable, instead of failing with a 500.

**Processing jobs**: `POST /api/ingest` returns a `job_id`. Poll `GET /api/jobs/{id}` to check status (`pending`, `completed`, `failed`). On completion, `anomalies_found` contains the count. On failure, `error` contains the traceback. The frontend polls automatically and shows the result.

### Querying Anomalies

The `/api/anomalies` endpoint is the main query interface. All parameters are optional and can be combined freely.

**Filtering:**

| Param | Description | Example |
|-------|-------------|---------|
| `sensor_id` | Filter by sensor | `TEMP_001` |
| `location` | Filter by location | `lab_a` |
| `anomaly_type` | Filter by metric | `temperature_anomaly`, `humidity_anomaly`, `pressure_anomaly` |
| `category` | Filter by classification | `spike`, `drift`, `sensor_failure`, `noise_burst` |
| `start` | Start of time range (ISO 8601) | `2024-01-01T00:00:00Z` |
| `end` | End of time range (ISO 8601) | `2024-01-02T00:00:00Z` |

**Sorting:**

| Param | Description | Values |
|-------|-------------|--------|
| `sort_by` | Column to sort on | `timestamp`, `sensor_id`, `location`, `anomaly_type`, `category`, `temperature`, `humidity`, `pressure`, `confidence_score` |
| `sort_dir` | Sort direction | `asc` (default), `desc` |

**Pagination:**

| Param | Description | Default |
|-------|-------------|---------|
| `limit` | Results per page (1–1000) | `100` |
| `offset` | Number of results to skip | `0` |

**Examples:**

```bash
# All anomalies, default pagination
curl "http://localhost:8080/api/anomalies"

# Anomalies for a specific sensor
curl "http://localhost:8080/api/anomalies?sensor_id=TEMP_001"

# Anomalies in a date range
curl "http://localhost:8080/api/anomalies?start=2024-01-01T00:00:00Z&end=2024-01-02T00:00:00Z"

# Spikes in lab_a, sorted by confidence descending
curl "http://localhost:8080/api/anomalies?category=spike&location=lab_a&sort_by=confidence_score&sort_dir=desc"

# Pressure anomalies from TEMP_001, page 2
curl "http://localhost:8080/api/anomalies?anomaly_type=pressure_anomaly&sensor_id=TEMP_001&limit=50&offset=50"
```

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
├── bruno/
│   ├── bruno.json          # Collection config
│   ├── environments/       # Environment variables (baseUrl)
│   └── *.bru               # 11 API request files (health, ingest, anomalies, etc.)
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

**Anomaly alerts:**
- **SensorFailureDetected** — any sensor failure anomaly detected (severity: critical)
- **AnomalySpike** — more than 5 spike anomalies from a single sensor in 5 minutes
- **SensorDrift** — more than 3 drift anomalies from a single sensor in 5 minutes
- **NoiseBurst** — more than 3 noise burst anomalies from a single sensor in 5 minutes
- **HighAnomalyRate** — more than 100 total anomalies across all sensors in 5 minutes

**Infrastructure alerts:**
- **HighErrorRate** — >5% of requests returning 5xx for 2 minutes
- **HighLatency** — p95 latency above 2s for 5 minutes
- **APIDown** — FastAPI metrics endpoint unreachable for 1 minute
- **PostgreSQLDown** — PostgreSQL exporter unreachable for 1 minute
- **HighDatabaseConnections** — >80 active connections for 5 minutes
- **NginxDown** — nginx exporter unreachable for 1 minute

Anomaly alerts include the sensor ID, metric, and count in the alert description. All alerts appear in Grafana's Alerting UI. To receive notifications (email, Slack, PagerDuty), configure a contact point in Grafana under Alerting > Contact points.

### Structured Logging

The API emits JSON-structured logs with `timestamp`, `level`, `name`, and `message` fields. Key events logged:
- CSV ingestion (readings count, job ID)
- Anomaly detection completion (job ID, anomalies found)
- Anomaly detection failures (with traceback)

Logs from all containers are collected by Promtail and queryable in Grafana via the Loki datasource.

### Using Metrics and Alerts

**Grafana** (http://localhost:3000, `admin`/`admin`) is the main interface for monitoring. Here's how to use it:

**Check the pre-built dashboard:**

1. Go to Dashboards → Pipeline Overview.
2. The top row shows request rate and error rate. A spike in errors after an upload likely means a malformed CSV or a detection failure.
3. The latency panels (p50/p95/p99) show how long API responses take. If p95 jumps during anomaly detection, that's normal — the `/ingest` endpoint does synchronous DB writes. If p95 stays high on `/anomalies` queries, you may need a database index.
4. The PostgreSQL panels show connection count and table row estimates. Watch for connection count creeping up — it suggests leaked sessions.

**Query logs:**

1. In Grafana, go to Explore → select the Loki datasource.
2. Use LogQL queries to find specific events:
   - All API logs: `{container_name=~".*api.*"}`
   - Anomaly detection results: `{container_name=~".*api.*"} |= "Detected" | json`
   - Errors only: `{container_name=~".*api.*"} | json | level="ERROR"`
   - Logs for a specific job: `{container_name=~".*api.*"} |= "job_id" | json | job_id=5`

**Check alert status:**

1. Go to Alerting → Alert rules in Grafana.
2. Each rule shows its current state: OK, Pending, or Firing.
3. To test alerting, stop the API container (`docker compose stop api`) and wait ~1 minute — the **APIDown** alert should fire.
4. To receive notifications, configure a contact point under Alerting → Contact points (supports email, Slack, PagerDuty, webhooks).

**Query Prometheus directly:**

Prometheus is available at http://localhost:9090 for ad-hoc metric queries:

- `rate(http_requests_total[5m])` — request rate over 5 minutes
- `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` — p99 latency
- `pg_stat_activity_count` — active PostgreSQL connections
- `http_requests_total{status=~"5.."}` — total 5xx error count
- `up` — which scrape targets are reachable (1 = up, 0 = down)

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
