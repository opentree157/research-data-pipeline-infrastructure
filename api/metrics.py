from prometheus_client import Counter

anomalies_detected_total = Counter(
    "anomalies_detected_total",
    "Total anomalies detected by the pipeline",
    ["sensor_id", "category", "metric"],
)
