import csv
import time
import argparse
import requests
from datetime import datetime


def query_prometheus(prom_url: str, query: str) -> float:
    response = requests.get(
        f"{prom_url}/api/v1/query",
        params={"query": query},
        timeout=10,
    )
    response.raise_for_status()

    result = response.json()["data"]["result"]

    if not result:
        return 0.0

    return float(result[0]["value"][1])


def main():
    parser = argparse.ArgumentParser(description="Export Prometheus metrics to CSV")
    parser.add_argument("--prom-url", default="http://localhost:9090")
    parser.add_argument("--output", default="data/raw/metrics.csv")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--duration", type=int, default=720)

    args = parser.parse_args()

    queries = {
        "rps": 'sum(rate(http_requests_total{endpoint!="/metrics", endpoint!="/health"}[1m]))',

        "p95_latency": '''
            histogram_quantile(
              0.95,
              sum(rate(http_request_duration_seconds_bucket{endpoint!="/metrics", endpoint!="/health"}[1m])) by (le)
            )
        ''',

        "error_rate": '''
            sum(rate(http_requests_total{http_status=~"5..", endpoint!="/metrics", endpoint!="/health"}[1m]))
            /
            clamp_min(sum(rate(http_requests_total{endpoint!="/metrics", endpoint!="/health"}[1m])), 0.0001)
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

        "in_progress_requests": '''
            sum(http_requests_in_progress{endpoint!="/metrics", endpoint!="/health"})
        ''',

        "synthetic_cpu_percent": '''
            avg(app_custom_cpu_usage_percent)
        '''
    }

    fieldnames = [
        "timestamp",
        "datetime",
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "pod_count",
        "in_progress_requests",
        "synthetic_cpu_percent",
    ]

    print(f"Writing metrics to {args.output}")

    with open(args.output, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        start_time = time.time()

        while time.time() - start_time < args.duration:
            row = {
                "timestamp": int(time.time()),
                "datetime": datetime.utcnow().isoformat(),
            }

            for metric_name, promql in queries.items():
                try:
                    row[metric_name] = query_prometheus(args.prom_url, promql)
                except Exception as e:
                    print(f"Failed to query {metric_name}: {e}")
                    row[metric_name] = 0.0

            writer.writerow(row)
            csvfile.flush()

            print(row)
            time.sleep(args.interval)


if __name__ == "__main__":
    main()