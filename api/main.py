import logging
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
    SensorReadingOut,
)

logging.basicConfig(level=logging.INFO)
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


def _run_detection(job_id: int, reading_ids: list[int]):
    db = SessionLocal()
    try:
        count = detect_anomalies(db, reading_ids)
        job = db.get(ProcessingJob, job_id)
        job.status = "completed"
        job.anomalies_found = count
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
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
    return IngestResponse(readings_ingested=len(reading_ids), job_id=job.id)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/anomalies", response_model=list[AnomalyDetail])
def get_anomalies(
    start: Optional[datetime] = Query(None, description="Start datetime (ISO 8601)"),
    end: Optional[datetime] = Query(None, description="End datetime (ISO 8601)"),
    sensor_id: Optional[str] = Query(None, description="Filter by sensor ID"),
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

    query = query.order_by(Anomaly.detected_at.desc(), Anomaly.id.desc())
    return query.offset(offset).limit(limit).all()


@app.get("/sensors", response_model=list[str])
def list_sensors(db: Session = Depends(get_db)):
    rows = db.query(SensorReading.sensor_id).distinct().all()
    return sorted(r[0] for r in rows)


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
