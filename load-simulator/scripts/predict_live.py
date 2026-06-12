import argparse
import csv
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import requests


FEATURE_QUERIES = {"rps", "p95_latency", "error_rate", "cpu_mcores", "in_progress_requests"}

# Safe replacements for live Prometheus gaps. During idle periods some PromQL
# expressions, especially histogram_quantile(), can return NaN. sklearn MLP
# models cannot predict with NaN/Inf inputs, so we normalize them here.
DEFAULT_SAFE_METRIC_VALUES = {
    "rps": 0.0,
    "p95_latency": 0.0,
    "error_rate": 0.0,
    "cpu_mcores": 0.0,
    "in_progress_requests": 0.0,
    "current_pods": 0.0,
    "desired_replicas": 0.0,
}


def is_finite_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def sanitize_metrics(metrics: dict) -> tuple[dict, dict]:
    """Replace NaN/Inf/missing metric values with safe defaults.

    Returns:
      sanitized_metrics, sanitized_flags

    Example flag:
      {"p95_latency": 1} means p95_latency was NaN/Inf/missing and was replaced.
    """
    sanitized = {}
    flags = {}

    for key, default_value in DEFAULT_SAFE_METRIC_VALUES.items():
        value = metrics.get(key, default_value)
        if is_finite_number(value):
            sanitized[key] = float(value)
            flags[key] = 0
        else:
            sanitized[key] = float(default_value)
            flags[key] = 1

    # Preserve any extra metrics that may be added later.
    for key, value in metrics.items():
        if key in sanitized:
            continue
        if is_finite_number(value):
            sanitized[key] = float(value)
            flags[key] = 0
        else:
            sanitized[key] = 0.0
            flags[key] = 1

    return sanitized, flags


def build_promql(endpoint_label: str, status_label: str, namespace: str, deployment: str, container: str):
    endpoint_filter = f'{endpoint_label}!="/metrics",{endpoint_label}!="/health"'
    pod_regex = f"{deployment}-.*"

    return {
        "rps": f'''
            sum(rate(http_requests_total{{{endpoint_filter}}}[1m]))
        ''',
        "p95_latency": f'''
            histogram_quantile(
              0.95,
              sum(rate(http_request_duration_seconds_bucket{{{endpoint_filter}}}[1m])) by (le)
            )
        ''',
        "error_rate": f'''
            sum(rate(http_requests_total{{{status_label}=~"5..",{endpoint_filter}}}[1m]))
            /
            clamp_min(sum(rate(http_requests_total{{{endpoint_filter}}}[1m])), 0.0001)
        ''',
        "cpu_mcores": f'''
            sum(rate(container_cpu_usage_seconds_total{{
              namespace="{namespace}",
              pod=~"{pod_regex}",
              container="{container}"
            }}[1m])) * 1000
        ''',
        "in_progress_requests": f'''
            sum(http_requests_in_progress{{{endpoint_filter}}})
        ''',
        "current_pods": f'''
            kube_deployment_status_replicas_available{{
              namespace="{namespace}",
              deployment="{deployment}"
            }}
        ''',
        "desired_replicas": f'''
            kube_deployment_spec_replicas{{
              namespace="{namespace}",
              deployment="{deployment}"
            }}
        ''',
    }


def round_pods(value: float, method: str) -> int:
    if method == "ceil":
        return int(math.ceil(value))
    if method == "floor":
        return int(math.floor(value))
    if method == "round":
        return int(round(value))
    raise ValueError(f"Unsupported rounding method: {method}")


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def query_prometheus(prom_url: str, query: str, timeout: int, retries: int, retry_sleep: float) -> float:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                f"{prom_url.rstrip('/')}/api/v1/query",
                params={"query": query},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()

            if payload.get("status") != "success":
                raise RuntimeError(f"Prometheus query failed: {payload}")

            result = payload.get("data", {}).get("result", [])
            if not result:
                return 0.0

            return float(result[0]["value"][1])
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_sleep)

    raise RuntimeError(f"Prometheus query failed after {retries} attempts: {last_error}")


def build_input(metrics: dict, features: list[str]) -> pd.DataFrame:
    missing = [feature for feature in features if feature not in metrics]
    if missing:
        raise ValueError(
            "The model expects features that this live script does not query: "
            + ", ".join(missing)
        )

    row = {}
    for feature in features:
        value = metrics[feature]
        if not is_finite_number(value):
            value = DEFAULT_SAFE_METRIC_VALUES.get(feature, 0.0)
        row[feature] = float(value)

    df = pd.DataFrame([row])
    # Final safety net before sklearn predict().
    df = df.replace([float("inf"), float("-inf")], 0.0).fillna(0.0)
    return df


def get_scale_direction(recommended_pods: int, reference_replicas: int) -> str:
    if recommended_pods > reference_replicas:
        return "scale_up"
    if recommended_pods < reference_replicas:
        return "scale_down"
    return "none"


def apply_hpa_like_policy(reference_replicas: int, recommended_pods: int, args) -> int:
    """
    Applies an HPA/KEDA-like rate limit to the target replica count.

    This mirrors the experiment YAMLs at a practical level:
      - scaleUp: selectPolicy Max over 100% / 15s and +2 pods / 15s
      - scaleDown: 50% / 30s, with scale-down cooldown/stabilization handled separately
    """
    if not args.hpa_like_policy:
        return recommended_pods

    if recommended_pods > reference_replicas:
        percent_delta = math.ceil(reference_replicas * args.scale_up_percent_limit / 100.0)
        pods_delta = args.scale_up_pods_limit
        allowed_delta = max(percent_delta, pods_delta)
        return min(recommended_pods, reference_replicas + allowed_delta)

    if recommended_pods < reference_replicas:
        percent_delta = math.floor(reference_replicas * args.scale_down_percent_limit / 100.0)
        allowed_delta = max(1, percent_delta)
        return max(recommended_pods, reference_replicas - allowed_delta)

    return recommended_pods


def append_csv(path: str, row: dict):
    if not path:
        return

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output_path.exists()

    fieldnames = [
        "timestamp_utc",
        "model_name",
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "in_progress_requests",
        "current_pods",
        "desired_replicas",
        "sanitized_metrics",
        "reference_replicas",
        "idle_detected",
        "idle_sample_count",
        "idle_guard_applied",
        "raw_prediction",
        "recommended_pods",
        "scale_target_pods",
        "scale_direction",
        "latency_slo_violation",
        "error_slo_violation",
        "slo_violation",
        "cooldown_required_seconds",
        "seconds_since_last_scale",
        "action",
    ]

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def scale_deployment(namespace: str, deployment: str, replicas: int):
    command = [
        "kubectl",
        "-n",
        namespace,
        "scale",
        "deployment",
        deployment,
        f"--replicas={replicas}",
    ]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor live Prometheus metrics and optionally scale a deployment using an ML model"
    )

    parser.add_argument("--model", default="models/best_model.joblib")
    parser.add_argument("--prom-url", default="http://127.0.0.1:19090")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--deployment", default="autoscale-test-service")
    parser.add_argument("--container", default="ats")
    parser.add_argument("--endpoint-label", default="exported_endpoint")
    parser.add_argument("--status-label", default="http_status")

    parser.add_argument("--min-pods", type=int, default=1)
    parser.add_argument("--max-pods", type=int, default=60)
    parser.add_argument("--rounding", choices=["ceil", "round", "floor"], default="ceil")

    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=0, help="0 means run forever")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)

    parser.add_argument("--latency-slo-threshold", type=float, default=0.5)
    parser.add_argument("--error-rate-slo-threshold", type=float, default=0.05)

    parser.add_argument(
        "--idle-guard",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Force recommended pods to min-pods when the service is clean idle for "
            "--idle-consecutive-samples samples. Use --no-idle-guard to disable."
        ),
    )
    parser.add_argument("--idle-rps-threshold", type=float, default=0.5)
    parser.add_argument("--idle-in-progress-threshold", type=float, default=0.5)
    parser.add_argument("--idle-consecutive-samples", type=int, default=2)

    parser.add_argument("--output-csv", default="results/metrics/ml_live_predictions.csv")

    parser.add_argument(
        "--apply-scale",
        action="store_true",
        help="Actually scale the deployment. Default is monitor-only/dry-run.",
    )

    # Backward-compatible parameter. If used, it overrides both directional cooldowns.
    parser.add_argument("--cooldown-seconds", type=int, default=None, help=argparse.SUPPRESS)

    parser.add_argument("--scale-up-cooldown-seconds", type=int, default=15)
    parser.add_argument("--scale-down-cooldown-seconds", type=int, default=60)
    parser.add_argument("--min-change", type=int, default=1)

    parser.add_argument(
        "--hpa-like-policy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply HPA/KEDA-like scale rate limits. Use --no-hpa-like-policy to scale directly to the ML recommendation.",
    )
    parser.add_argument("--scale-up-percent-limit", type=int, default=100)
    parser.add_argument("--scale-up-pods-limit", type=int, default=2)
    parser.add_argument("--scale-down-percent-limit", type=int, default=50)

    args = parser.parse_args()

    if args.cooldown_seconds is not None:
        args.scale_up_cooldown_seconds = args.cooldown_seconds
        args.scale_down_cooldown_seconds = args.cooldown_seconds

    if args.min_pods < 1:
        raise ValueError("--min-pods must be at least 1")
    if args.max_pods < args.min_pods:
        raise ValueError("--max-pods must be greater than or equal to --min-pods")
    if args.min_change < 1:
        raise ValueError("--min-change must be at least 1")
    if args.idle_consecutive_samples < 1:
        raise ValueError("--idle-consecutive-samples must be at least 1")

    artifact = joblib.load(args.model)
    model = artifact["model"]
    features = artifact["features"]
    model_name = artifact.get("model_name", "unknown")

    unsupported = [feature for feature in features if feature not in FEATURE_QUERIES]
    if unsupported:
        raise ValueError(
            "This script can only query these model features: "
            + ", ".join(sorted(FEATURE_QUERIES))
            + ". Unsupported model features: "
            + ", ".join(unsupported)
        )

    promql = build_promql(
        endpoint_label=args.endpoint_label,
        status_label=args.status_label,
        namespace=args.namespace,
        deployment=args.deployment,
        container=args.container,
    )

    print("Live ML autoscaling monitor started.")
    print(f"Model: {model_name}")
    print(f"Prometheus: {args.prom_url}")
    print(f"Deployment: {args.namespace}/{args.deployment}")
    print(f"Mode: {'APPLY SCALE' if args.apply_scale else 'DRY-RUN / monitor only'}")
    print(f"Interval: {args.interval}s")
    print(f"Scale-up cooldown: {args.scale_up_cooldown_seconds}s")
    print(f"Scale-down cooldown: {args.scale_down_cooldown_seconds}s")
    print(f"Min change: {args.min_change} pod")
    print(f"HPA-like policy: {args.hpa_like_policy}")
    print(f"SLO thresholds: p95>{args.latency_slo_threshold}s OR error_rate>{args.error_rate_slo_threshold}")
    print(
        f"Idle guard: {args.idle_guard} "
        f"(rps<={args.idle_rps_threshold}, "
        f"in_progress<={args.idle_in_progress_threshold}, "
        f"samples={args.idle_consecutive_samples})"
    )
    print("")

    last_scale_time = 0.0
    iteration = 0
    idle_sample_count = 0

    try:
        while True:
            iteration += 1
            timestamp_utc = datetime.now(timezone.utc).isoformat()

            metrics = {}
            for metric_name, query in promql.items():
                metrics[metric_name] = query_prometheus(
                    args.prom_url,
                    query,
                    timeout=args.timeout,
                    retries=args.retries,
                    retry_sleep=args.retry_sleep,
                )

            metrics, sanitized_flags = sanitize_metrics(metrics)

            input_data = build_input(metrics, features)
            raw_prediction = float(model.predict(input_data)[0])
            model_recommended_pods = clamp(
                round_pods(raw_prediction, args.rounding),
                args.min_pods,
                args.max_pods,
            )

            idle_detected = (
                metrics.get("rps", 0.0) <= args.idle_rps_threshold
                and metrics.get("in_progress_requests", 0.0) <= args.idle_in_progress_threshold
            )
            if idle_detected:
                idle_sample_count += 1
            else:
                idle_sample_count = 0

            idle_guard_applied = bool(
                args.idle_guard
                and idle_sample_count >= args.idle_consecutive_samples
            )

            if idle_guard_applied:
                recommended_pods = args.min_pods
            else:
                recommended_pods = model_recommended_pods

            latency_slo_violation = 1 if metrics["p95_latency"] > args.latency_slo_threshold else 0
            error_slo_violation = 1 if metrics["error_rate"] > args.error_rate_slo_threshold else 0
            slo_violation = 1 if latency_slo_violation or error_slo_violation else 0

            current_pods = int(round(metrics.get("current_pods", 0)))
            desired_replicas = int(round(metrics.get("desired_replicas", 0)))
            reference_replicas = desired_replicas if desired_replicas > 0 else current_pods
            reference_replicas = clamp(reference_replicas, args.min_pods, args.max_pods)

            # ------------------------------------------------------------
            # Safety guard 1:
            # If SLO is violated, never scale down.
            # During latency/error violation, reducing replicas can make the
            # service unstable. Keep at least the current/reference replica count.
            # ------------------------------------------------------------
            if slo_violation:
                recommended_pods = max(recommended_pods, reference_replicas)

            # ------------------------------------------------------------
            # Safety guard 2:
            # Avoid aggressive scale-down while meaningful traffic is still active.
            # This prevents sudden drops such as 60 -> 30 while requests are ongoing.
            # ------------------------------------------------------------
            if metrics["rps"] > 30 and recommended_pods < reference_replicas:
                recommended_pods = max(
                    recommended_pods,
                    math.ceil(reference_replicas * 0.85)
                )

            scale_target_pods = apply_hpa_like_policy(reference_replicas, recommended_pods, args)
            scale_target_pods = clamp(scale_target_pods, args.min_pods, args.max_pods)

            scale_direction = get_scale_direction(scale_target_pods, reference_replicas)
            now = time.time()
            seconds_since_last_scale = now - last_scale_time if last_scale_time > 0 else 999999.0

            if scale_direction == "scale_up":
                cooldown_required_seconds = args.scale_up_cooldown_seconds
            elif scale_direction == "scale_down":
                cooldown_required_seconds = args.scale_down_cooldown_seconds
            else:
                cooldown_required_seconds = 0

            action = "dry_run"

            if args.apply_scale:
                enough_change = abs(scale_target_pods - reference_replicas) >= args.min_change
                cooldown_ok = seconds_since_last_scale >= cooldown_required_seconds

                if scale_direction == "none":
                    action = "no_scale_same_replicas"
                elif not enough_change:
                    action = "no_scale_min_change"
                elif not cooldown_ok:
                    action = f"no_scale_cooldown_{scale_direction}"
                else:
                    scale_deployment(args.namespace, args.deployment, scale_target_pods)
                    action = f"{scale_direction}_to_{scale_target_pods}"
                    last_scale_time = now

            row = {
                "timestamp_utc": timestamp_utc,
                "model_name": model_name,
                **metrics,
                "sanitized_metrics": ",".join([k for k, v in sanitized_flags.items() if v]),
                "current_pods": current_pods,
                "desired_replicas": desired_replicas,
                "reference_replicas": reference_replicas,
                "idle_detected": int(idle_detected),
                "idle_sample_count": idle_sample_count,
                "idle_guard_applied": int(idle_guard_applied),
                "raw_prediction": raw_prediction,
                "recommended_pods": recommended_pods,
                "scale_target_pods": scale_target_pods,
                "scale_direction": scale_direction,
                "latency_slo_violation": latency_slo_violation,
                "error_slo_violation": error_slo_violation,
                "slo_violation": slo_violation,
                "cooldown_required_seconds": cooldown_required_seconds,
                "seconds_since_last_scale": round(seconds_since_last_scale, 3),
                "action": action,
            }
            append_csv(args.output_csv, row)

            print(
                f"[{timestamp_utc}] "
                f"rps={metrics['rps']:.2f} "
                f"p95={metrics['p95_latency']:.3f}s "
                f"err={metrics['error_rate']:.4f} "
                f"cpu={metrics['cpu_mcores']:.1f}m "
                f"inflight={metrics['in_progress_requests']:.1f} "
                f"current={current_pods} desired={desired_replicas} ref={reference_replicas} "
                f"raw={raw_prediction:.2f} model_rec={model_recommended_pods} recommended={recommended_pods} target={scale_target_pods} "
                f"idle={int(idle_detected)}/{idle_sample_count} idle_guard={int(idle_guard_applied)} "
                f"dir={scale_direction} slo={slo_violation} action={action}"
            )

            if args.iterations > 0 and iteration >= args.iterations:
                break

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
