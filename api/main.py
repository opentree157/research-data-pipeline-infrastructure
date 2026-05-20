import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from anomaly_detector import detect_anomalies
from database import SessionLocal, get_db
from ingest import ingest_csv
from models import Anomaly, SensorReading
from schemas import AnomalyDetail, HealthResponse, IngestResponse, SensorReadingOut

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
    root_path="/api",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_detection(reading_ids: list[int]):
    db = SessionLocal()
    try:
        detect_anomalies(db, reading_ids)
    finally:
        db.close()


@app.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    readings_count = db.query(SensorReading).count()
    anomalies_count = db.query(Anomaly).count()

    return HealthResponse(
        status="healthy",
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
    content = (await file.read()).decode("utf-8")
    reading_ids = ingest_csv(db, content)
    background_tasks.add_task(_run_detection, reading_ids)
    return IngestResponse(
        readings_ingested=len(reading_ids),
        anomalies_detected=0,
        processing=True,
    )


@app.get("/anomalies", response_model=list[AnomalyDetail])
def get_anomalies(
    start: Optional[datetime] = Query(None, description="Start datetime (ISO 8601)"),
    end: Optional[datetime] = Query(None, description="End datetime (ISO 8601)"),
    sensor_id: Optional[str] = Query(None, description="Filter by sensor ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Anomaly).join(SensorReading)

    if start:
        query = query.filter(SensorReading.timestamp >= start)
    if end:
        query = query.filter(SensorReading.timestamp <= end)
    if sensor_id:
        query = query.filter(SensorReading.sensor_id == sensor_id)

    query = query.order_by(Anomaly.detected_at.desc())
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
