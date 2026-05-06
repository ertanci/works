import argparse
from pathlib import Path

import pandas as pd


DEFAULT_FEATURE_COLUMNS = [
    "rps",
    "p95_latency",
    "error_rate",
    "cpu_mcores",
    "in_progress_requests",
]

OPTIONAL_FEATURE_COLUMNS = [
    "pod_count",
]

DEFAULT_TARGET_COLUMN = "desired_replicas"


def parse_columns(value):
    if not value:
        return []
    return [col.strip() for col in value.split(",") if col.strip()]


def ensure_numeric(df, columns):
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clean exported Prometheus metrics and split them into train/test CSV files "
            "for ML-based pod count prediction."
        )
    )

    parser.add_argument("--input", required=True, help="Input raw metrics CSV file")
    parser.add_argument("--train-output", default="results/metrics/ml_train.csv")
    parser.add_argument("--test-output", default="results/metrics/ml_test.csv")
    parser.add_argument("--clean-output", default="results/metrics/ml_dataset_step_load.csv")

    parser.add_argument("--test-size", type=float, default=0.2, help="Test ratio, e.g. 0.2 for 80/20 split")
    parser.add_argument(
        "--scenario",
        default="step-load",
        help="Scenario to use for ML training. Default: step-load. Use 'all' to include all non-idle scenarios.",
    )
    parser.add_argument(
        "--target-column",
        default=DEFAULT_TARGET_COLUMN,
        help="Target column to predict. Default: desired_replicas",
    )
    parser.add_argument(
        "--features",
        default=",".join(DEFAULT_FEATURE_COLUMNS),
        help="Comma-separated feature columns. Default: rps,p95_latency,error_rate,cpu_mcores,in_progress_requests",
    )
    parser.add_argument(
        "--include-pod-count-feature",
        action="store_true",
        help=(
            "Include current pod_count as an input feature. "
            "Default is false to avoid making the target too directly dependent on current replica state."
        ),
    )
    parser.add_argument(
        "--split-method",
        choices=["time", "random"],
        default="time",
        help="Use chronological split by timestamp or random split. Default: time",
    )
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--min-rps",
        type=float,
        default=0.0,
        help="Minimum RPS to keep. Default 0.0 keeps all non-idle rows with valid RPS.",
    )

    args = parser.parse_args()

    if not 0 < args.test_size < 1:
        raise ValueError("--test-size must be between 0 and 1, e.g. 0.2")

    df_raw = pd.read_csv(args.input)
    raw_rows = len(df_raw)

    df = df_raw.copy()

    # 1. Remove idle rows. These are waiting/scale-down gaps and should not train the ML model.
    if "scenario" in df.columns:
        df = df[df["scenario"] != "idle"].copy()

        if args.scenario != "all":
            df = df[df["scenario"] == args.scenario].copy()

    # 2. Select features and target.
    feature_columns = parse_columns(args.features)

    if args.include_pod_count_feature:
        for col in OPTIONAL_FEATURE_COLUMNS:
            if col not in feature_columns:
                feature_columns.append(col)

    required_columns = feature_columns + [args.target_column]

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Missing required columns in input CSV: " + ", ".join(missing_columns)
        )

    # Keep metadata columns if present for traceability in the cleaned dataset.
    metadata_columns = [
        "timestamp",
        "datetime_utc",
        "run_id",
        "scenario",
        "autoscaler",
        "set_no",
        "target_vus",
        "baseline_vus",
        "spike_target_vus",
    ]
    metadata_columns = [col for col in metadata_columns if col in df.columns]

    numeric_columns = list(dict.fromkeys(required_columns + ["rps", "p95_latency", "error_rate"]))
    df = ensure_numeric(df, numeric_columns)

    # 3. Clean invalid or empty rows.
    df = df.dropna(subset=required_columns)

    if "rps" in df.columns:
        df = df[df["rps"] > args.min_rps]
    if "p95_latency" in df.columns:
        df = df[df["p95_latency"] >= 0]
    if "error_rate" in df.columns:
        df = df[df["error_rate"] >= 0]
    if "cpu_mcores" in df.columns:
        df = df[df["cpu_mcores"] >= 0]
    if "in_progress_requests" in df.columns:
        df = df[df["in_progress_requests"] >= 0]
    if args.target_column in df.columns:
        df = df[df[args.target_column] >= 1]

    # 4. Rename target to a thesis-friendly name.
    df = df.rename(columns={args.target_column: "required_pods"})
    target_column = "required_pods"

    # 5. Sort chronologically before splitting unless random split is requested.
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    output_columns = metadata_columns + feature_columns + [target_column]
    # If target was present in metadata somehow, remove duplicates while preserving order.
    output_columns = list(dict.fromkeys(output_columns))

    dataset = df[output_columns].copy()

    if len(dataset) < 2:
        raise ValueError("Not enough rows after cleaning to split train/test dataset")

    # 6. Split train/test.
    if args.split_method == "random":
        dataset_for_split = dataset.sample(frac=1, random_state=args.random_state).reset_index(drop=True)
    else:
        dataset_for_split = dataset

    split_index = int(len(dataset_for_split) * (1 - args.test_size))

    train_df = dataset_for_split.iloc[:split_index].copy()
    test_df = dataset_for_split.iloc[split_index:].copy()

    # 7. Save outputs.
    Path(args.clean_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.train_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.test_output).parent.mkdir(parents=True, exist_ok=True)

    dataset.to_csv(args.clean_output, index=False)
    train_df.to_csv(args.train_output, index=False)
    test_df.to_csv(args.test_output, index=False)

    print("Preprocessing completed.")
    print(f"Input rows: {raw_rows}")
    print(f"Rows after cleaning: {len(dataset)}")
    print(f"Scenario filter: {args.scenario}")
    print(f"Split method: {args.split_method}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
    print(f"Features: {', '.join(feature_columns)}")
    print(f"Target: {target_column}")
    print(f"Clean file: {args.clean_output}")
    print(f"Train file: {args.train_output}")
    print(f"Test file: {args.test_output}")


if __name__ == "__main__":
    main()
