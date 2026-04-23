from fastapi import FastAPI, Response, Query
import time
import random
import math
import asyncio
from prometheus_client import Counter, Histogram, Gauge, generate_latest

app = FastAPI(title="AutoScale Test Service")

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0),
)

CPU_USAGE_GAUGE = Gauge(
    "app_custom_cpu_usage_percent",
    "Simulated application CPU usage percentage",
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of active in-progress HTTP requests",
    ["endpoint"],
)


def cpu_intensive_task(duration: float) -> None:
    """Run CPU-intensive work for the given duration in seconds."""
    end_time = time.time() + duration
    while time.time() < end_time:
        math.sqrt(random.random()) * math.exp(random.random())


async def handle_request(
    endpoint_name: str,
    delay: float,
    error_rate: int,
    cpu_load: float,
):
    start_time = time.time()
    request_timestamp = time.time()
    status_code = 200

    REQUESTS_IN_PROGRESS.labels(endpoint=endpoint_name).inc()

    try:
        # Simulated CPU workload
        if cpu_load > 0:
            await asyncio.to_thread(cpu_intensive_task, cpu_load)
            simulated_cpu = min(100.0, 10.0 + (cpu_load * 100.0))
            CPU_USAGE_GAUGE.set(simulated_cpu)
        else:
            CPU_USAGE_GAUGE.set(5.0 + random.uniform(0, 5))

        # Simulated latency
        if delay > 0:
            await asyncio.sleep(delay)

        # Simulated error response
        if random.randint(1, 100) <= error_rate:
            status_code = 500
            return Response(
                content="Internal Server Error",
                status_code=status_code,
                media_type="text/plain",
            )

        return {
            "status": "ok",
            "endpoint": endpoint_name,
            "timestamp": request_timestamp,
            "latency_seconds": round(time.time() - start_time, 4),
            "cpu_load_applied": cpu_load,
            "delay_applied": delay,
            "error_rate_applied": error_rate,
        }

    finally:
        latency = time.time() - start_time
        REQUEST_COUNT.labels(
            method="GET",
            endpoint=endpoint_name,
            http_status=str(status_code),
        ).inc()
        REQUEST_LATENCY.labels(endpoint=endpoint_name).observe(latency)
        REQUESTS_IN_PROGRESS.labels(endpoint=endpoint_name).dec()


@app.get("/")
async def root(
    delay: float = Query(0.15, ge=0.0, le=10.0, description="Artificial delay in seconds"),
    error_rate: int = Query(5, ge=0, le=100, description="Error rate percentage between 0 and 100"),
    cpu_load: float = Query(0.05, ge=0.0, le=5.0, description="CPU load duration in seconds"),
):
    return await handle_request(
        endpoint_name="/",
        delay=delay,
        error_rate=error_rate,
        cpu_load=cpu_load,
    )


@app.get("/light")
async def light(
    delay: float = Query(0.05, ge=0.0, le=10.0),
    error_rate: int = Query(1, ge=0, le=100),
    cpu_load: float = Query(0.01, ge=0.0, le=5.0),
):
    return await handle_request(
        endpoint_name="/light",
        delay=delay,
        error_rate=error_rate,
        cpu_load=cpu_load,
    )


@app.get("/heavy")
async def heavy(
    delay: float = Query(0.2, ge=0.0, le=10.0),
    error_rate: int = Query(5, ge=0, le=100),
    cpu_load: float = Query(0.2, ge=0.0, le=5.0),
):
    return await handle_request(
        endpoint_name="/heavy",
        delay=delay,
        error_rate=error_rate,
        cpu_load=cpu_load,
    )


@app.get("/error")
async def error(
    delay: float = Query(0.1, ge=0.0, le=10.0),
    error_rate: int = Query(40, ge=0, le=100),
    cpu_load: float = Query(0.03, ge=0.0, le=5.0),
):
    return await handle_request(
        endpoint_name="/error",
        delay=delay,
        error_rate=error_rate,
        cpu_load=cpu_load,
    )


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )