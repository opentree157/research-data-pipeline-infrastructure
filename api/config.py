import os


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://pipeline:pipeline@db:5432/sensor_data",
)

ROLLING_WINDOW_SIZE = int(os.environ.get("ROLLING_WINDOW_SIZE", "20"))
ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", "2.0"))

API_ROOT_PATH = os.environ.get("API_ROOT_PATH", "/api")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
