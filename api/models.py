from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from database import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    sensor_id = Column(String(50), nullable=False, index=True)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    pressure = Column(Float, nullable=False)
    location = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    anomalies = relationship("Anomaly", back_populates="reading")


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        UniqueConstraint("sensor_data_id", "anomaly_type", name="uq_anomaly_reading_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_data_id = Column(
        Integer, ForeignKey("sensor_readings.id"), nullable=False, index=True
    )
    anomaly_type = Column(String(50), nullable=False)
    confidence_score = Column(Float, nullable=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())

    reading = relationship("SensorReading", back_populates="anomalies")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), nullable=False, default="pending")
    readings_count = Column(Integer, nullable=False)
    anomalies_found = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
