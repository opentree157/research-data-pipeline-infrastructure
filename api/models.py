from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_data_id = Column(
        Integer, ForeignKey("sensor_readings.id"), nullable=False, index=True
    )
    anomaly_type = Column(String(50), nullable=False)
    confidence_score = Column(Float, nullable=False)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())

    reading = relationship("SensorReading", back_populates="anomalies")
