#!/usr/bin/env python3
"""
Tez sonuç tablosu üretim scripti.

Bu script, Kubernetes autoscaling deneyleri sonucunda oluşan k6 summary JSON
dosyalarını okur ve tezde kullanılabilecek karşılaştırma tablosu üretir.

İncelediği dosyalar:
  - results/k6/step-load/..._summary.json
  - results/k6/spike-load/..._summary.json
  - results/k6/poisson-arrival-rate/..._summary.json

Karşılaştırılan senaryolar:
  - step: kademeli yük artışı
  - spike: ani trafik artışı
  - poisson: Poisson dağılımlı değişken trafik

Karşılaştırılan yöntemler:
  - HPA
  - KEDA
  - MLP
  - Linear Regression
  - SVR

Üretilen metrikler:
  - p95 latency
  - ortalama latency
  - hata oranı
  - ortalama RPS
  - toplam istek sayısı

Çıktılar:
  - results/metrics/thesis_k6_results_table.csv
  - results/metrics/thesis_k6_results_table.md
  - results/metrics/thesis_autoscaling_results_table.csv
  - results/metrics/thesis_autoscaling_results_table.md

Not:
  k6 tablosu k6 summary dosyalarına göre üretilir. Autoscaling tablosu ise
  results/metrics/metrics_20260613.csv dosyasındaki Prometheus/export
  metriklerinden hesaplanır. Hangi zaman aralığının hangi senaryo ve yönteme
  ait olduğu results/full_experiment_20260613_015333.log dosyasından çıkarılır.
  MLP, Linear ve SVR deneyleri logda genel olarak ML adıyla geçtiği için
  13 Haziran deney sırasına göre MLP -> Linear -> SVR olarak eşlenir.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ExperimentFile:
    scenario: str
    method: str
    path: str


@dataclass(frozen=True)
class ExperimentInterval:
    scenario: str
    method: str
    start_ts: float
    end_ts: float


# Bu liste 2026-06-13 tarihinde alınan karşılaştırmalı deney çıktılarından
# oluşturulmuştur. Step senaryosunda her yöntem için 50, 100, 200 ve 400 VU
# koşuları vardır. Spike ve Poisson senaryolarında her yöntem için bir koşu vardır.
SELECTED_EXPERIMENT_FILES = [
    # Step-load / HPA
    ExperimentFile("step", "HPA", "results/k6/step-load/20260613_015527_HPA_Set1_50VUs_summary.json"),
    ExperimentFile("step", "HPA", "results/k6/step-load/20260613_020621_HPA_Set1_100VUs_summary.json"),
    ExperimentFile("step", "HPA", "results/k6/step-load/20260613_021936_HPA_Set1_200VUs_summary.json"),
    ExperimentFile("step", "HPA", "results/k6/step-load/20260613_023731_HPA_Set1_400VUs_summary.json"),

    # Step-load / KEDA
    ExperimentFile("step", "KEDA", "results/k6/step-load/20260613_030114_KEDA_Set1_50VUs_summary.json"),
    ExperimentFile("step", "KEDA", "results/k6/step-load/20260613_031137_KEDA_Set1_100VUs_summary.json"),
    ExperimentFile("step", "KEDA", "results/k6/step-load/20260613_032431_KEDA_Set1_200VUs_summary.json"),
    ExperimentFile("step", "KEDA", "results/k6/step-load/20260613_034105_KEDA_Set1_400VUs_summary.json"),

    # Step-load / MLP
    ExperimentFile("step", "MLP", "results/k6/step-load/20260613_052612_ML_Set1_50VUs_summary.json"),
    ExperimentFile("step", "MLP", "results/k6/step-load/20260613_053454_ML_Set1_100VUs_summary.json"),
    ExperimentFile("step", "MLP", "results/k6/step-load/20260613_054658_ML_Set1_200VUs_summary.json"),
    ExperimentFile("step", "MLP", "results/k6/step-load/20260613_060323_ML_Set1_400VUs_summary.json"),

    # Step-load / Linear Regression
    ExperimentFile("step", "Linear", "results/k6/step-load/20260613_070505_ML_Set1_50VUs_summary.json"),
    ExperimentFile("step", "Linear", "results/k6/step-load/20260613_071418_ML_Set1_100VUs_summary.json"),
    ExperimentFile("step", "Linear", "results/k6/step-load/20260613_072530_ML_Set1_200VUs_summary.json"),
    ExperimentFile("step", "Linear", "results/k6/step-load/20260613_074125_ML_Set1_400VUs_summary.json"),

    # Step-load / SVR
    ExperimentFile("step", "SVR", "results/k6/step-load/20260613_084057_ML_Set1_50VUs_summary.json"),
    ExperimentFile("step", "SVR", "results/k6/step-load/20260613_090319_ML_Set1_100VUs_summary.json"),
    ExperimentFile("step", "SVR", "results/k6/step-load/20260613_092742_ML_Set1_200VUs_summary.json"),
    ExperimentFile("step", "SVR", "results/k6/step-load/20260613_095611_ML_Set1_400VUs_summary.json"),

    # Spike-load
    ExperimentFile("spike", "HPA", "results/k6/spike-load/20260613_040709_HPA_Spike_Set1_50_to_400_summary.json"),
    ExperimentFile("spike", "KEDA", "results/k6/spike-load/20260613_041935_KEDA_Spike_Set1_50_to_400_summary.json"),
    ExperimentFile("spike", "MLP", "results/k6/spike-load/20260613_062539_ML_Spike_Set1_50_to_400_summary.json"),
    ExperimentFile("spike", "Linear", "results/k6/spike-load/20260613_080343_ML_Spike_Set1_50_to_400_summary.json"),
    ExperimentFile("spike", "SVR", "results/k6/spike-load/20260613_101738_ML_Spike_Set1_50_to_400_summary.json"),

    # Poisson arrival-rate
    ExperimentFile("poisson", "HPA", "results/k6/poisson-arrival-rate/20260613_043527_HPA_Poisson_Set1_Mean110RPS_summary.json"),
    ExperimentFile("poisson", "KEDA", "results/k6/poisson-arrival-rate/20260613_045936_KEDA_Poisson_Set1_Mean110RPS_summary.json"),
    ExperimentFile("poisson", "MLP", "results/k6/poisson-arrival-rate/20260613_063902_ML_Poisson_Set1_Mean110RPS_summary.json"),
    ExperimentFile("poisson", "Linear", "results/k6/poisson-arrival-rate/20260613_081627_ML_Poisson_Set1_Mean110RPS_summary.json"),
    ExperimentFile("poisson", "SVR", "results/k6/poisson-arrival-rate/20260613_104332_ML_Poisson_Set1_Mean110RPS_summary.json"),
]


SCENARIO_ORDER = ["step", "spike", "poisson"]
METHOD_ORDER = ["HPA", "KEDA", "MLP", "Linear", "SVR"]


AUTOSCALING_INPUT_FILES = [
    "results/metrics/metrics_20260613.csv"
]

EXPERIMENT_LOG_FILE = "results/full_experiment_20260613_015333.log"
LOG_TIMEZONE = "Europe/Istanbul"
ML_METHOD_SEQUENCE = ["MLP", "Linear", "SVR"]


def read_k6_summary(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_metrics(summary: dict) -> dict:
    metrics = summary.get("metrics", {})
    duration = metrics.get("http_req_duration", {})
    failed = metrics.get("http_req_failed", {})
    requests = metrics.get("http_reqs", {})

    return {
        "p95_latency_ms": duration.get("p(95)"),
        "avg_latency_ms": duration.get("avg"),
        "error_rate": failed.get("value"),
        "avg_rps": requests.get("rate"),
        "total_requests": requests.get("count"),
    }


def average(values: Iterable[float | int | None]) -> float | None:
    clean_values = [float(value) for value in values if value is not None]
    if not clean_values:
        return None
    return sum(clean_values) / len(clean_values)


def build_rows(workspace: Path) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}

    for item in SELECTED_EXPERIMENT_FILES:
        full_path = workspace / item.path
        if not full_path.exists():
            raise FileNotFoundError(f"Experiment summary not found: {full_path}")

        summary = read_k6_summary(full_path)
        metrics = extract_metrics(summary)
        grouped.setdefault((item.scenario, item.method), []).append(metrics)

    rows = []
    for scenario in SCENARIO_ORDER:
        for method in METHOD_ORDER:
            group = grouped.get((scenario, method), [])
            if not group:
                continue

            p95_latency_ms = average(row["p95_latency_ms"] for row in group)
            avg_latency_ms = average(row["avg_latency_ms"] for row in group)
            error_rate = average(row["error_rate"] for row in group)
            avg_rps = average(row["avg_rps"] for row in group)
            total_requests = sum(int(row["total_requests"] or 0) for row in group)

            rows.append(
                {
                    "scenario": scenario,
                    "method": method,
                    "run_count": len(group),
                    "p95_latency_ms": round(p95_latency_ms or 0, 3),
                    "avg_latency_ms": round(avg_latency_ms or 0, 3),
                    "error_rate_percent": round((error_rate or 0) * 100, 3),
                    "avg_rps": round(avg_rps or 0, 3),
                    "total_requests": total_requests,
                }
            )

    return rows


def write_csv(rows: list[dict], output_path: Path, fieldnames: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_k6_markdown(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| Senaryo | Yöntem | Koşum | p95 ms | Avg latency ms | Error % | Avg RPS | Total req |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| {scenario} | {method} | {run_count} | {p95_latency_ms:.1f} | "
            "{avg_latency_ms:.1f} | {error_rate_percent:.2f} | {avg_rps:.1f} | "
            "{total_requests} |".format(**row)
        )

    lines.extend(
        [
            "",
            "**Kolon açıklamaları**",
            "",
            "- **Senaryo:** Deneyde kullanılan yük tipi. `step` kademeli yük artışını, `spike` ani trafik artışını, `poisson` ise Poisson dağılımlı değişken trafik davranışını ifade eder.",
            "- **Yöntem:** Karşılaştırılan otomatik ölçeklendirme yaklaşımıdır. HPA, KEDA, MLP, Linear Regression ve SVR yöntemlerini içerir.",
            "- **Koşum:** İlgili senaryo-yöntem kombinasyonu için kaç ayrı k6 summary dosyasının tabloya dahil edildiğini gösterir.",
            "- **p95 ms:** İsteklerin yüzde 95'inin altında kaldığı gecikme süresidir. Değerin düşük olması kullanıcı deneyimi açısından daha iyidir.",
            "- **Avg latency ms:** Tüm isteklerin ortalama yanıt süresidir. Genel response time davranışını gösterir.",
            "- **Error %:** k6 sonucuna göre başarısız istek oranıdır. Yüzde olarak verilmiştir.",
            "- **Avg RPS:** Test süresince gerçekleşen ortalama saniyelik istek sayısıdır.",
            "- **Total req:** İlgili koşumlarda gönderilen toplam HTTP istek sayısıdır.",
        ]
    )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_scenario(value: str) -> str | None:
    value = (value or "").strip().lower()
    if value in {"step", "step-load", "step_load"}:
        return "step"
    if value in {"spike", "spike-load", "spike_load"}:
        return "spike"
    if value in {"poisson", "poisson-arrival-rate", "poisson_arrival_rate"}:
        return "poisson"
    return None


def normalize_method(value: str) -> str | None:
    value = (value or "").strip().lower()
    if value == "hpa":
        return "HPA"
    if value == "keda":
        return "KEDA"
    if value in {"ml", "mlp"}:
        return "MLP"
    if value in {"linear", "linear_regression", "linear-regression"}:
        return "Linear"
    if value in {"svr", "vector"}:
        return "SVR"
    return None


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_metrics_rows(workspace: Path) -> list[dict]:
    rows: list[dict] = []

    for relative_path in AUTOSCALING_INPUT_FILES:
        path = workspace / relative_path
        if not path.exists():
            continue

        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["_source_file"] = relative_path
                rows.append(row)

    return rows


def median_step_seconds(timestamps: list[float]) -> float:
    unique_timestamps = sorted(set(timestamps))
    diffs = [
        unique_timestamps[index] - unique_timestamps[index - 1]
        for index in range(1, len(unique_timestamps))
        if unique_timestamps[index] > unique_timestamps[index - 1]
    ]
    if not diffs:
        return 5.0

    diffs.sort()
    middle = len(diffs) // 2
    if len(diffs) % 2:
        return diffs[middle]
    return (diffs[middle - 1] + diffs[middle]) / 2


def parse_log_timestamp(value: str) -> float:
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=ZoneInfo(LOG_TIMEZONE)).timestamp()


def parse_experiment_intervals(workspace: Path) -> list[ExperimentInterval]:
    """Read the full experiment log and derive scenario/method time windows.

    HPA and KEDA intervals are explicitly logged as START/END LOAD or TEST.
    ML-based runs are logged generically as ML, so the method is inferred from
    the known 2026-06-13 run order: MLP, Linear, SVR. Each method has step,
    spike and poisson blocks in that order.
    """
    log_path = workspace / EXPERIMENT_LOG_FILE
    if not log_path.exists():
        raise FileNotFoundError(f"Experiment log not found: {log_path}")

    start_load_re = re.compile(
        r"\[(?P<time>[^\]]+)\] START LOAD \| autoscaler=(?P<method>HPA|KEDA) .* target_vus=(?P<target>\d+)"
    )
    end_load_re = re.compile(
        r"\[(?P<time>[^\]]+)\] END LOAD \| autoscaler=(?P<method>HPA|KEDA) .* target_vus=(?P<target>\d+)"
    )
    start_test_re = re.compile(
        r"\[(?P<time>[^\]]+)\] START (?P<scenario>SPIKE|POISSON) TEST \| autoscaler=(?P<method>HPA|KEDA)"
    )
    end_test_re = re.compile(
        r"\[(?P<time>[^\]]+)\] END (?P<scenario>SPIKE|POISSON) TEST \| autoscaler=(?P<method>HPA|KEDA)"
    )
    start_ml_experiment_re = re.compile(
        r"\[(?P<time>[^\]]+)\] START ML (?P<scenario>STEP|SPIKE|POISSON) EXPERIMENT"
    )
    start_ml_load_re = re.compile(
        r"\[(?P<time>[^\]]+)\] START ML (?P<scenario>STEP|SPIKE|POISSON) LOAD"
    )
    stop_ml_re = re.compile(r"\[(?P<time>[^\]]+)\] Stopping ML autoscaler")

    intervals: list[ExperimentInterval] = []
    active: dict[tuple[str, str, str], float] = {}

    ml_block_index = -1
    current_ml_method: str | None = None
    current_ml_scenario: str | None = None
    current_ml_start: float | None = None

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := start_load_re.search(line):
            key = ("step", match.group("method"), match.group("target"))
            active[key] = parse_log_timestamp(match.group("time"))
            continue

        if match := end_load_re.search(line):
            key = ("step", match.group("method"), match.group("target"))
            start_ts = active.pop(key, None)
            if start_ts is not None:
                intervals.append(
                    ExperimentInterval("step", match.group("method"), start_ts, parse_log_timestamp(match.group("time")))
                )
            continue

        if match := start_test_re.search(line):
            scenario = normalize_scenario(match.group("scenario"))
            method = match.group("method")
            if scenario:
                active[(scenario, method, "test")] = parse_log_timestamp(match.group("time"))
            continue

        if match := end_test_re.search(line):
            scenario = normalize_scenario(match.group("scenario"))
            method = match.group("method")
            if scenario:
                start_ts = active.pop((scenario, method, "test"), None)
                if start_ts is not None:
                    intervals.append(
                        ExperimentInterval(scenario, method, start_ts, parse_log_timestamp(match.group("time")))
                    )
            continue

        if match := start_ml_experiment_re.search(line):
            ml_block_index += 1
            current_ml_method = ML_METHOD_SEQUENCE[min(ml_block_index // 3, len(ML_METHOD_SEQUENCE) - 1)]
            current_ml_scenario = normalize_scenario(match.group("scenario"))
            current_ml_start = None
            continue

        if match := start_ml_load_re.search(line):
            scenario = normalize_scenario(match.group("scenario"))
            if current_ml_method and scenario == current_ml_scenario and current_ml_start is None:
                current_ml_start = parse_log_timestamp(match.group("time"))
            continue

        if match := stop_ml_re.search(line):
            if current_ml_method and current_ml_scenario and current_ml_start is not None:
                intervals.append(
                    ExperimentInterval(
                        current_ml_scenario,
                        current_ml_method,
                        current_ml_start,
                        parse_log_timestamp(match.group("time")),
                    )
                )
            current_ml_start = None
            current_ml_scenario = None
            current_ml_method = None

    return intervals


def find_interval(timestamp: float, intervals: list[ExperimentInterval]) -> ExperimentInterval | None:
    for interval in intervals:
        if interval.start_ts <= timestamp <= interval.end_ts:
            return interval
    return None


def build_autoscaling_rows(workspace: Path) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    intervals = parse_experiment_intervals(workspace)

    for row in read_metrics_rows(workspace):
        timestamp = parse_float(row.get("timestamp"))
        if timestamp is None:
            continue

        interval = find_interval(timestamp, intervals)
        if interval is None:
            continue

        grouped.setdefault((interval.scenario, interval.method), []).append(row)

    rows: list[dict] = []
    for scenario in SCENARIO_ORDER:
        for method in METHOD_ORDER:
            group = grouped.get((scenario, method), [])

            if not group:
                rows.append(
                    {
                        "scenario": scenario,
                        "method": method,
                        "sample_count": 0,
                        "slo_violation_minutes": "N/A",
                        "latency_slo_violation_minutes": "N/A",
                        "error_slo_violation_minutes": "N/A",
                        "avg_pod_count": "N/A",
                        "max_pod_count": "N/A",
                        "avg_cpu_mcores": "N/A",
                        "max_cpu_mcores": "N/A",
                    }
                )
                continue

            timestamps = [
                value
                for value in (parse_float(row.get("timestamp")) for row in group)
                if value is not None
            ]
            step_seconds = median_step_seconds(timestamps)

            latency_flags = []
            error_flags = []
            total_flags = []
            pod_values = []
            cpu_values = []

            for row in group:
                p95_latency = parse_float(row.get("p95_latency"))
                error_rate = parse_float(row.get("error_rate"))
                latency_flag = parse_float(row.get("latency_slo_violation"))
                error_flag = parse_float(row.get("error_slo_violation"))
                total_flag = parse_float(row.get("slo_violation") or row.get("total_slo_violation"))

                if latency_flag is None:
                    latency_flag = 1.0 if p95_latency is not None and p95_latency > 0.5 else 0.0
                if error_flag is None:
                    error_flag = 1.0 if error_rate is not None and error_rate > 0.05 else 0.0
                if total_flag is None:
                    total_flag = 1.0 if latency_flag or error_flag else 0.0

                latency_flags.append(latency_flag)
                error_flags.append(error_flag)
                total_flags.append(total_flag)

                pod_value = parse_float(row.get("current_pods") or row.get("pod_count"))
                cpu_value = parse_float(row.get("cpu_mcores"))
                if pod_value is not None:
                    pod_values.append(pod_value)
                if cpu_value is not None:
                    cpu_values.append(cpu_value)

            def minutes(flags: list[float]) -> float:
                return round(sum(1 for flag in flags if flag >= 1.0) * step_seconds / 60.0, 3)

            rows.append(
                {
                    "scenario": scenario,
                    "method": method,
                    "sample_count": len(group),
                    "slo_violation_minutes": minutes(total_flags),
                    "latency_slo_violation_minutes": minutes(latency_flags),
                    "error_slo_violation_minutes": minutes(error_flags),
                    "avg_pod_count": round(average(pod_values) or 0, 3) if pod_values else "N/A",
                    "max_pod_count": round(max(pod_values), 3) if pod_values else "N/A",
                    "avg_cpu_mcores": round(average(cpu_values) or 0, 3) if cpu_values else "N/A",
                    "max_cpu_mcores": round(max(cpu_values), 3) if cpu_values else "N/A",
                }
            )

    return rows


def write_autoscaling_markdown(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| Senaryo | Yöntem | Örnek | SLO ihlal dk | Latency SLO dk | Error SLO dk | Avg pod | Max pod | Avg CPU mcores | Max CPU mcores |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| {scenario} | {method} | {sample_count} | {slo_violation_minutes} | "
            "{latency_slo_violation_minutes} | {error_slo_violation_minutes} | "
            "{avg_pod_count} | {max_pod_count} | {avg_cpu_mcores} | {max_cpu_mcores} |".format(**row)
        )

    lines.extend(
        [
            "",
            "**Kolon açıklamaları**",
            "",
            "- **Senaryo:** Deneyde kullanılan yük tipidir.",
            "- **Yöntem:** Karşılaştırılan autoscaling yaklaşımıdır.",
            "- **Örnek:** Prometheus/export CSV içinde ilgili senaryo-yöntem için kullanılan satır sayısıdır.",
            "- **SLO ihlal dk:** `p95_latency > 0.5` veya `error_rate > 0.05` olduğu toplam süredir.",
            "- **Latency SLO dk:** Sadece p95 gecikme eşiğinin aşıldığı toplam süredir.",
            "- **Error SLO dk:** Sadece hata oranı eşiğinin aşıldığı toplam süredir.",
            "- **Avg pod / Max pod:** Deney sırasında gözlenen ortalama ve maksimum pod sayısıdır.",
            "- **Avg CPU mcores / Max CPU mcores:** Deney sırasında gözlenen ortalama ve maksimum CPU tüketimidir.",
        ]
    )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build thesis k6 and autoscaling comparison tables."
    )
    parser.add_argument("--workspace", default=".", help="Repository/workspace root directory.")
    parser.add_argument(
        "--k6-csv-output",
        default="results/metrics/thesis_k6_results_table.csv",
        help="k6 performance CSV output path.",
    )
    parser.add_argument(
        "--k6-markdown-output",
        default="results/metrics/thesis_k6_results_table.md",
        help="k6 performance Markdown output path.",
    )
    parser.add_argument(
        "--autoscaling-csv-output",
        default="results/metrics/thesis_autoscaling_results_table.csv",
        help="Autoscaling/resource CSV output path.",
    )
    parser.add_argument(
        "--autoscaling-markdown-output",
        default="results/metrics/thesis_autoscaling_results_table.md",
        help="Autoscaling/resource Markdown output path.",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    k6_rows = build_rows(workspace)
    autoscaling_rows = build_autoscaling_rows(workspace)

    k6_csv_output = workspace / args.k6_csv_output
    k6_markdown_output = workspace / args.k6_markdown_output
    autoscaling_csv_output = workspace / args.autoscaling_csv_output
    autoscaling_markdown_output = workspace / args.autoscaling_markdown_output

    write_csv(
        k6_rows,
        k6_csv_output,
        [
            "scenario",
            "method",
            "run_count",
            "p95_latency_ms",
            "avg_latency_ms",
            "error_rate_percent",
            "avg_rps",
            "total_requests",
        ],
    )
    write_k6_markdown(k6_rows, k6_markdown_output)

    write_csv(
        autoscaling_rows,
        autoscaling_csv_output,
        [
            "scenario",
            "method",
            "sample_count",
            "slo_violation_minutes",
            "latency_slo_violation_minutes",
            "error_slo_violation_minutes",
            "avg_pod_count",
            "max_pod_count",
            "avg_cpu_mcores",
            "max_cpu_mcores",
        ],
    )
    write_autoscaling_markdown(autoscaling_rows, autoscaling_markdown_output)

    print(f"k6 rows written: {len(k6_rows)}")
    print(f"k6 CSV: {k6_csv_output}")
    print(f"k6 Markdown: {k6_markdown_output}")
    print(f"Autoscaling rows written: {len(autoscaling_rows)}")
    print(f"Autoscaling CSV: {autoscaling_csv_output}")
    print(f"Autoscaling Markdown: {autoscaling_markdown_output}")


if __name__ == "__main__":
    main()
