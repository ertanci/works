import argparse
from pathlib import Path

import pandas as pd


def calculate_target_pods(row, max_pods):
    current_pods = int(round(row["pod_count"]))

    latency_violation = row["p95_latency"] > 0.5
    error_violation = row["error_rate"] > 0.05

    target_pods = current_pods

    if latency_violation:
        target_pods += 1

    if error_violation:
        target_pods += 1

    if row["in_progress_requests"] > 20:
        target_pods += 1

    target_pods = max(1, min(target_pods, max_pods))

    return target_pods


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess metrics dataset and generate SLO-aware target labels"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--train-output", default="data/processed/train.csv")
    parser.add_argument("--test-output", default="data/processed/test.csv")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--max-pods", type=int, default=10)

    args = parser.parse_args()

    df = pd.read_csv(args.input)

    numeric_columns = [
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "pod_count",
        "in_progress_requests",
        "synthetic_cpu_percent",
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=[
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "pod_count",
        "in_progress_requests",
    ])

    df = df[df["rps"] >= 0]
    df = df[df["p95_latency"] >= 0]
    df = df[df["error_rate"] >= 0]
    df = df[df["cpu_mcores"] >= 0]
    df = df[df["pod_count"] >= 1]
    df = df[df["in_progress_requests"] >= 0]

    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")

    df["target_pod_count"] = df.apply(
        lambda row: calculate_target_pods(row, args.max_pods),
        axis=1,
    )

    feature_columns = [
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "in_progress_requests",
        "pod_count",
    ]

    output_columns = feature_columns + ["target_pod_count"]

    dataset = df[output_columns].copy()

    split_index = int(len(dataset) * (1 - args.test_size))

    train_df = dataset.iloc[:split_index]
    test_df = dataset.iloc[split_index:]

    Path(args.train_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.test_output).parent.mkdir(parents=True, exist_ok=True)

    train_df.to_csv(args.train_output, index=False)
    test_df.to_csv(args.test_output, index=False)

    print("Preprocessing completed.")
    print(f"Input rows: {len(df)}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
    print(f"Train file: {args.train_output}")
    print(f"Test file: {args.test_output}")


if __name__ == "__main__":
    main()