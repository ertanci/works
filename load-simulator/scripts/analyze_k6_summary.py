import json
import sys

file_path = sys.argv[1]

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metrics = data["metrics"]

summary = {
    "file": file_path,
    "http_reqs": metrics.get("http_reqs", {}).get("count"),
    "rps": metrics.get("http_reqs", {}).get("rate"),
    "error_rate": metrics.get("http_req_failed", {}).get("rate"),
    "avg_latency_ms": metrics.get("http_req_duration", {}).get("avg"),
    "p90_latency_ms": metrics.get("http_req_duration", {}).get("percentiles", {}).get("90"),
    "p95_latency_ms": metrics.get("http_req_duration", {}).get("percentiles", {}).get("95"),
    "p99_latency_ms": metrics.get("http_req_duration", {}).get("percentiles", {}).get("99"),
}

for k, v in summary.items():
    print(f"{k}: {v}")