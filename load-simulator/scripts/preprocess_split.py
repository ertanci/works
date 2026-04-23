import argparse
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess metrics dataset and split chronologically"
    )

    parser.add_argument("--input", required=True)
    parser.add_argument("--train-output", default="data/processed/train.csv")
    parser.add_argument("--test-output", default="data/processed/test.csv")
    parser.add_argument("--test-size", type=float, default=0.2)

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
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=numeric_columns)

    df = df[df["rps"] >= 0]
    df = df[df["p95_latency"] >= 0]
    df = df[df["error_rate"] >= 0]
    df = df[df["cpu_mcores"] >= 0]
    df = df[df["pod_count"] >= 1]

    # Zaman sırasını koru
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")

    # Target: gözlenen pod sayısı
    df["target_pod_count"] = df["pod_count"].round().astype(int)

    feature_columns = [
        "rps",
        "p95_latency",
        "error_rate",
        "cpu_mcores",
        "in_progress_requests",
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