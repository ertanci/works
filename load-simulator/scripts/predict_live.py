import argparse
import math
import requests
import joblib
import pandas as pd


PROMQL_QUERIES = {
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

    "in_progress_requests": '''
        sum(http_requests_in_progress{endpoint!="/metrics", endpoint!="/health"})
    '''
}


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
    parser = argparse.ArgumentParser(
        description="Predict required pod count from live Prometheus metrics"
    )

    parser.add_argument("--model", default="models/best_model.joblib")
    parser.add_argument("--prom-url", default="http://localhost:9090")
    parser.add_argument("--min-pods", type=int, default=1)
    parser.add_argument("--max-pods", type=int, default=10)

    args = parser.parse_args()

    artifact = joblib.load(args.model)
    model = artifact["model"]
    features = artifact["features"]

    metrics = {}

    for metric_name, promql in PROMQL_QUERIES.items():
        metrics[metric_name] = query_prometheus(args.prom_url, promql)

    input_data = pd.DataFrame([metrics])
    input_data = input_data[features]

    raw_prediction = model.predict(input_data)[0]

    recommended_pods = math.ceil(raw_prediction)
    recommended_pods = max(args.min_pods, min(args.max_pods, recommended_pods))

    print("Live prediction completed.")
    print(f"Model: {artifact['model_name']}")
    print("")
    print("Live metrics:")
    for key, value in metrics.items():
        print(f"  {key}: {value:.4f}")

    print("")
    print(f"Raw prediction: {raw_prediction:.3f}")
    print(f"Recommended pod count: {recommended_pods}")


if __name__ == "__main__":
    main()