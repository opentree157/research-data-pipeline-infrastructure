import logging
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger.json import JsonFormatter as JsonFormatter
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from anomaly_detector import detect_anomalies
from config import ALLOWED_ORIGINS, API_ROOT_PATH
from database import SessionLocal, get_db
from ingest import ValidationError, ingest_csv
from models import Anomaly, ProcessingJob, SensorReading
from schemas import (
    AnomalyDetail,
    HealthResponse,
    IngestResponse,
    JobStatusResponse,
    PaginatedAnomalies,
    SensorReadingOut,
)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    rename_fields={"asctime": "timestamp", "levelname": "level"},
))
logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("TESTING"):
        yield
        return
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations applied")
    yield


app = FastAPI(
    title="Research Data Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=API_ROOT_PATH,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator(
    excluded_handlers=["/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def _run_detection(job_id: int, reading_ids: list[int]):
    db = SessionLocal()
    try:
        count = detect_anomalies(db, reading_ids)
        job = db.get(ProcessingJob, job_id)
        job.status = "completed"
        job.anomalies_found = count
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Anomaly detection completed", extra={"job_id": job_id, "anomalies_found": count})
    except Exception:
        logger.exception("Anomaly detection failed for job %d", job_id)
        try:
            job = db.get(ProcessingJob, job_id)
            job.status = "failed"
            job.error = traceback.format_exc()[-500:]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            logger.exception("Failed to update job %d status", job_id)
    finally:
        db.close()


@app.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
        readings_count = db.query(SensorReading).count()
        anomalies_count = db.query(Anomaly).count()
    except Exception:
        db_status = "disconnected"
        readings_count = 0
        anomalies_count = 0

    status = "healthy" if db_status == "connected" else "degraded"
    return HealthResponse(
        status=status,
        database=db_status,
        readings_count=readings_count,
        anomalies_count=anomalies_count,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8")

    try:
        reading_ids = ingest_csv(db, content)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job = ProcessingJob(status="pending", readings_count=len(reading_ids))
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_detection, job.id, reading_ids)
    logger.info("CSV ingested", extra={"readings": len(reading_ids), "job_id": job.id})
    return IngestResponse(readings_ingested=len(reading_ids), job_id=job.id)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


SORT_COLUMNS = {
    "timestamp": SensorReading.timestamp,
    "sensor_id": SensorReading.sensor_id,
    "location": SensorReading.location,
    "anomaly_type": Anomaly.anomaly_type,
    "category": Anomaly.category,
    "temperature": SensorReading.temperature,
    "humidity": SensorReading.humidity,
    "pressure": SensorReading.pressure,
    "confidence_score": Anomaly.confidence_score,
}


@app.get("/anomalies", response_model=PaginatedAnomalies)
def get_anomalies(
    start: Optional[datetime] = Query(None, description="Start datetime (ISO 8601)"),
    end: Optional[datetime] = Query(None, description="End datetime (ISO 8601)"),
    sensor_id: Optional[str] = Query(None, description="Filter by sensor ID"),
    location: Optional[str] = Query(None, description="Filter by location"),
    anomaly_type: Optional[str] = Query(None, description="Filter by anomaly type (metric)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    sort_by: Optional[str] = Query(None, description="Sort column"),
    sort_dir: Optional[str] = Query("asc", description="Sort direction: asc or desc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Anomaly)
        .join(SensorReading)
        .options(joinedload(Anomaly.reading))
    )

    if start:
        query = query.filter(SensorReading.timestamp >= start)
    if end:
        query = query.filter(SensorReading.timestamp <= end)
    if sensor_id:
        query = query.filter(SensorReading.sensor_id == sensor_id)
    if location:
        query = query.filter(SensorReading.location == location)
    if anomaly_type:
        query = query.filter(Anomaly.anomaly_type == anomaly_type)
    if category:
        query = query.filter(Anomaly.category == category)

    total = query.count()

    col = SORT_COLUMNS.get(sort_by) if sort_by else None
    if col is not None:
        order = col.desc() if sort_dir == "desc" else col.asc()
        items = query.order_by(order, Anomaly.id).offset(offset).limit(limit).all()
    else:
        items = query.order_by(Anomaly.detected_at.desc(), Anomaly.id.desc()).offset(offset).limit(limit).all()

    return PaginatedAnomalies(items=items, total=total, limit=limit, offset=offset)


@app.get("/sensors", response_model=list[str])
def list_sensors(db: Session = Depends(get_db)):
    rows = db.query(SensorReading.sensor_id).distinct().all()
    return sorted(r[0] for r in rows)


@app.get("/locations", response_model=list[str])
def list_locations(db: Session = Depends(get_db)):
    rows = db.query(SensorReading.location).distinct().all()
    return sorted(r[0] for r in rows if r[0])


@app.get("/anomaly-types", response_model=list[str])
def list_anomaly_types(db: Session = Depends(get_db)):
    rows = db.query(Anomaly.anomaly_type).distinct().all()
    return sorted(r[0] for r in rows if r[0])


@app.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)):
    rows = db.query(Anomaly.category).distinct().all()
    return sorted(r[0] for r in rows if r[0])


@app.get("/readings", response_model=list[SensorReadingOut])
def get_readings(
    sensor_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(SensorReading)
    if sensor_id:
        query = query.filter(SensorReading.sensor_id == sensor_id)
    return query.order_by(SensorReading.timestamp.desc()).offset(offset).limit(limit).all()
