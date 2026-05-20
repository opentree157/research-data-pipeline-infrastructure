from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SensorReadingOut(BaseModel):
    id: int
    timestamp: datetime
    sensor_id: str
    temperature: float
    humidity: float
    pressure: float
    location: str

    model_config = {"from_attributes": True}


class AnomalyDetail(BaseModel):
    id: int
    sensor_data_id: int
    anomaly_type: str
    confidence_score: float
    detected_at: datetime
    reading: SensorReadingOut

    model_config = {"from_attributes": True}


class IngestResponse(BaseModel):
    readings_ingested: int
    job_id: int


class JobStatusResponse(BaseModel):
    id: int
    status: str
    readings_count: int
    anomalies_found: Optional[int]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    database: str
    readings_count: int
    anomalies_count: int
