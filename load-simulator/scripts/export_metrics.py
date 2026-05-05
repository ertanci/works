import csv
import argparse
import requests
import time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


LATENCY_SLO_SECONDS = 0.5
ERROR_SLO_RATE = 0.05


def parse_datetime_to_ts(value: str, timezone_name: str) -> int:
    """
    Converts a datetime string to Unix timestamp.

    Accepted formats:
      - 2026-05-06 01:00:00
      - 2026-05-06T01:00:00
      - 2026-05-06T01:00:00+03:00
      - 2026-05-06T01:00:00Z

    If timezone information is not included in the value,
    the timezone_name parameter is used.
    """
    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))

    return int(dt.timestamp())


def query_range(prom_url, query, start_ts, end_ts, step):
    response = requests.get(
        f"{prom_url}/api/v1/query_range",
        params={
            "query": query,
            "start": start_ts,
            "end": end_ts,
            "step": step,
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")

    result = payload.get("data", {}).get("result", [])

    if not result:
        return {}

    values = result[0].get("values", [])

    output = {}

    for ts, value in values:
        output[int(float(ts))] = float(value)

    return output


def load_timeline(path):
    timeline_path = Path(path)

    if not timeline_path.exists():
        print(f"WARNING: Timeline file not found: {timeline_path}")
        return []

    events = []

    with open(timeline_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            row["set_no"] = int(row.get("set_no", 0) or 0)
            row["target_vus"] = int(row.get("target_vus", 0) or 0)
            row["baseline_vus"] = int(row.get("baseline_vus", 0) or 0)
            row["spike_target_vus"] = int(row.get("spike_target_vus", 0) or 0)
            row["start_ts"] = int(float(row["start_ts"]))
            row["end_ts"] = int(float(row["end_ts"]))
            events.append(row)

    return events


def find_event_for_timestamp(events, ts):
    for event in events:
        if event["start_ts"] <= ts <= event["end_ts"]:
            return event

    return None


def main():
    parser = argparse.ArgumentParser(description="Export Prometheus range metrics to a single CSV")

    parser.add_argument("--prom-url", default="http://localhost:9090")
    parser.add_argument("--output", default="results/metrics/metrics_all.csv")
    parser.add_argument("--timeline", default="results/metrics/experiment_timeline.csv")

    # Option 1: Export a fixed date/time range.
    parser.add_argument("--start", default=None, help="Start datetime, e.g. '2026-05-06 01:00:00'")
    parser.add_argument("--end", default=None, help="End datetime, e.g. '2026-05-06 06:30:00'")
    parser.add_argument("--timezone", default="Europe/Istanbul", help="Timezone used when --start/--end have no offset")

    # Option 2: Export recent data using lookback.
    parser.add_argument("--lookback-minutes", type=int, default=120)

    # 5 seconds is recommended. Use 300 for 5 minutes.
    parser.add_argument("--step", type=int, default=5)

    args = parser.parse_args()

    if args.start and args.end:
        start_ts = parse_datetime_to_ts(args.start, args.timezone)
        end_ts = parse_datetime_to_ts(args.end, args.timezone)
    elif args.start or args.end:
        raise ValueError("Both --start and --end must be provided together.")
    else:
        end_ts = int(time.time())
        start_ts = end_ts - (args.lookback_minutes * 60)

    if start_ts >= end_ts:
        raise ValueError("--start must be earlier than --end")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    events = load_timeline(args.timeline)

    queries = {
        "rps": '''
            sum(rate(http_requests_total{
              exported_endpoint!="/metrics",
              exported_endpoint!="/health"
            }[1m]))
        ''',

        "p95_latency": '''
            histogram_quantile(
              0.95,
              sum(rate(http_request_duration_seconds_bucket{
                exported_endpoint!="/metrics",
                exported_endpoint!="/health"
              }[1m])) by (le)
            )
        ''',

        "p99_latency": '''
            histogram_quantile(
              0.99,
              sum(rate(http_request_duration_seconds_bucket{
                exported_endpoint!="/metrics",
                exported_endpoint!="/health"
              }[1m])) by (le)
            )
        ''',

        "error_rate": '''
            sum(rate(http_requests_total{
              http_status=~"5..",
              exported_endpoint!="/metrics",
              exported_endpoint!="/health"
            }[1m]))
            /
            clamp_min(
              sum(rate(http_requests_total{
                exported_endpoint!="/metrics",
                exported_endpoint!="/health"
              }[1m])),
              0.0001
            )
        ''',

        "cpu_mcores": '''
            sum(rate(container_cpu_usage_seconds_total{
              namespace="default",
              pod=~"autoscale-test-service-.*",
              container="ats"
            }[1m])) * 1000
        ''',

        "pod_count": '''
            kube_deployment_status_replicas_available{
              namespace="default",
              deployment="autoscale-test-service"
            }
        ''',

        "desired_replicas": '''
            kube_deployment_spec_replicas{
              namespace="default",
              deployment="autoscale-test-service"
            }
        ''',

        "in_progress_requests": '''
            sum(http_requests_in_progress{
              exported_endpoint!="/metrics",
              exported_endpoint!="/health"
            })
        ''',

        "synthetic_cpu_percent": '''
            avg(app_custom_cpu_usage_percent)
        ''',

        "hpa_active_observed": '''
            clamp_max(
              count(kube_horizontalpodautoscaler_info{
                namespace="default",
                horizontalpodautoscaler!~"keda-hpa-.*"
              }),
              1
            )
        ''',

        "keda_active_observed": '''
            clamp_max(
              count(kube_horizontalpodautoscaler_info{
                namespace="default",
                horizontalpodautoscaler=~"keda-hpa-.*"
              }),
              1
            )
        '''
    }

    print("Exporting Prometheus metrics")
    print(f"Prometheus URL: {args.prom_url}")
    print(f"Start UTC: {datetime.fromtimestamp(start_ts, timezone.utc).isoformat()}")
    print(f"End UTC:   {datetime.fromtimestamp(end_ts, timezone.utc).isoformat()}")
    print(f"Step: {args.step}s")
    print(f"Timeline: {args.timeline}")
    print(f"Output: {args.output}")

    metric_series = {}

    for metric_name, promql in queries.items():
        print(f"Querying {metric_name}...")
        metric_series[metric_name] = query_range(
            args.prom_url,
            promql,
            start_ts,
            end_ts,
            args.step,
        )

    timestamps = set()

    for series in metric_series.values():
        timestamps.update(series.keys())

    timestamps = sorted(timestamps)

    fieldnames = [
        "timestamp",
        "datetime_utc",

        "run_id",
        "scenario",
        "autoscaler",
        "set_no",
        "target_vus",
        "baseline_vus",
        "spike_target_vus",

        "rps",
        "p95_latency",
        "p99_latency",
        "error_rate",
        "cpu_mcores",
        "cpu_per_pod_mcores",
        "pod_count",
        "desired_replicas",
        "in_progress_requests",
        "synthetic_cpu_percent",

        "hpa_active_observed",
        "keda_active_observed",

        "latency_slo_violation",
        "error_slo_violation",
        "total_slo_violation",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for ts in timestamps:
            event = find_event_for_timestamp(events, ts)

            row = {
                "timestamp": ts,
                "datetime_utc": datetime.fromtimestamp(ts, timezone.utc).isoformat(),

                "run_id": event["run_id"] if event else "",
                "scenario": event["scenario"] if event else "idle",
                "autoscaler": event["autoscaler"] if event else "none",
                "set_no": event["set_no"] if event else 0,
                "target_vus": event["target_vus"] if event else 0,
                "baseline_vus": event["baseline_vus"] if event else 0,
                "spike_target_vus": event["spike_target_vus"] if event else 0,
            }

            for metric_name in queries.keys():
                row[metric_name] = metric_series[metric_name].get(ts, 0.0)

            pod_count = float(row.get("pod_count", 0) or 0)
            cpu_mcores = float(row.get("cpu_mcores", 0) or 0)

            if pod_count > 0:
                row["cpu_per_pod_mcores"] = cpu_mcores / pod_count
            else:
                row["cpu_per_pod_mcores"] = 0.0

            p95_latency = float(row.get("p95_latency", 0) or 0)
            error_rate = float(row.get("error_rate", 0) or 0)

            latency_slo_violation = 1 if p95_latency > LATENCY_SLO_SECONDS else 0
            error_slo_violation = 1 if error_rate > ERROR_SLO_RATE else 0

            row["latency_slo_violation"] = latency_slo_violation
            row["error_slo_violation"] = error_slo_violation
            row["total_slo_violation"] = 1 if latency_slo_violation or error_slo_violation else 0

            writer.writerow(row)

    print(f"Done. Rows written: {len(timestamps)}")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
