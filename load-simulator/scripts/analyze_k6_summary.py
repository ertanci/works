import json
import sys

file_path = sys.argv[1]

with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metrics = data["metrics"]

duration = metrics.get("http_req_duration", {})
failed = metrics.get("http_req_failed", {})
http_reqs = metrics.get("http_reqs", {})
iterations = metrics.get("iterations", {})
vus = metrics.get("vus", {})
vus_max = metrics.get("vus_max", {})

summary = {
    "file": file_path,
    "http_reqs": http_reqs.get("count"),
    "rps": http_reqs.get("rate"),
    "error_rate": failed.get("value"),
    "error_rate_percent": failed.get("value") * 100 if failed.get("value") is not None else None,
    "avg_latency_ms": duration.get("avg"),
    "min_latency_ms": duration.get("min"),
    "median_latency_ms": duration.get("med"),
    "max_latency_ms": duration.get("max"),
    "p90_latency_ms": duration.get("p(90)"),
    "p95_latency_ms": duration.get("p(95)"),
    "p99_latency_ms": duration.get("p(99)"),
    "iterations": iterations.get("count"),
    "iteration_rate": iterations.get("rate"),
    "vus_max": vus_max.get("max"),
    "vus_observed_max": vus.get("max"),
}

for k, v in summary.items():
    print(f"{k}: {v}")