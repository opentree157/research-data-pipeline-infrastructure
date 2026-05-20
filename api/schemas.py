from datetime import datetime
from typing import List, Optional

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


class AnomalyOut(BaseModel):
    id: int
    sensor_data_id: int
    anomaly_type: str
    confidence_score: float
    detected_at: datetime

    model_config = {"from_attributes": True}


class AnomalyDetail(AnomalyOut):
    reading: SensorReadingOut


class IngestResponse(BaseModel):
    readings_ingested: int
    anomalies_detected: int
    processing: bool = False


class HealthResponse(BaseModel):
    status: str
    database: str
    readings_count: int
    anomalies_count: int
