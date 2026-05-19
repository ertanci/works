import argparse
import warnings
from pathlib import Path

import pandas as pd


DEFAULT_FEATURE_COLUMNS = [
    "rps",
    "p95_latency",
    "error_rate",
    "cpu_mcores",
    "in_progress_requests",
]

DEFAULT_TARGET_CANDIDATES = ["required_pods", "desired_replicas"]
DEFAULT_CURRENT_PODS_CANDIDATES = [
    "current_pods",
    "pod_count",
    "running_pods",
    "ready_replicas",
    "available_replicas",
]
DEFAULT_ELAPSED_GROUP_COLUMNS = [
    "run_id",
    "autoscaler",
    "scenario",
    "set_no",
    "target_vus",
    "baseline_vus",
    "spike_target_vus",
]


# -------------------------
# Helper functions
# -------------------------

def parse_columns(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [col.strip() for col in str(value).split(",") if col.strip()]


def parse_number_list(value):
    """Parse a comma-separated number list such as '1,2,3' or '400'."""
    if value is None or str(value).strip() == "":
        return []
    return [float(item.strip()) for item in str(value).split(",") if item.strip()]


def format_number_list(values):
    output = []
    for value in values:
        if float(value).is_integer():
            output.append(str(int(value)))
        else:
            output.append(str(value))
    return ",".join(output)


def ensure_numeric(df, columns):
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def resolve_first_existing_column(df, candidates, purpose):
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(
        f"Could not find a column for {purpose}. Tried: {', '.join(candidates)}"
    )


def resolve_target_column(df, requested_target_column):
    if requested_target_column and requested_target_column != "auto":
        if requested_target_column not in df.columns:
            raise ValueError(
                f"Target column '{requested_target_column}' was not found in input CSV. "
                f"Available columns: {', '.join(df.columns)}"
            )
        return requested_target_column

    return resolve_first_existing_column(
        df,
        DEFAULT_TARGET_CANDIDATES,
        "target pod count / desired replicas",
    )


def add_current_pods_column(df, current_pods_candidates):
    """Create a normalized current_pods column if a source column exists.

    Important: this function does not fake current pod data. If no source column
    exists, current_pods is kept as NA so that the dataset schema is stable, but
    the user can see that the raw export must be improved.
    """
    candidates = parse_columns(current_pods_candidates)

    for col in candidates:
        if col in df.columns:
            df["current_pods"] = pd.to_numeric(df[col], errors="coerce")
            return df, col

    df["current_pods"] = pd.NA
    warnings.warn(
        "No current pod count column was found. Created current_pods as empty values. "
        "Export pod count from Kubernetes/Prometheus in the raw CSV to populate it. "
        f"Tried: {', '.join(candidates)}"
    )
    return df, None


def add_desired_replicas_column(df, target_column):
    """Ensure desired_replicas exists for traceability.

    If desired_replicas is not present, the chosen target column is copied into it.
    This is useful when older datasets already use required_pods as the target.
    """
    if "desired_replicas" not in df.columns:
        df["desired_replicas"] = pd.to_numeric(df[target_column], errors="coerce")
        source = target_column
    else:
        df["desired_replicas"] = pd.to_numeric(df["desired_replicas"], errors="coerce")
        source = "desired_replicas"

    return df, source


def timestamp_to_seconds(df):
    """Return a numeric timestamp series in seconds for sorting and elapsed time."""
    if "timestamp" in df.columns:
        ts = pd.to_numeric(df["timestamp"], errors="coerce")
        median_value = ts.dropna().median() if ts.notna().any() else None

        # Heuristic unit detection:
        # - seconds since epoch around 1e9
        # - milliseconds since epoch around 1e12
        # - nanoseconds since epoch around 1e18
        if median_value is not None:
            if median_value > 1e17:
                return ts / 1_000_000_000
            if median_value > 1e11:
                return ts / 1_000
            return ts

    if "datetime_utc" in df.columns:
        dt = pd.to_datetime(df["datetime_utc"], errors="coerce", utc=True)
        return dt.astype("int64") / 1_000_000_000

    warnings.warn(
        "No timestamp or datetime_utc column was found. elapsed_seconds will be based on row order."
    )
    return pd.Series(range(len(df)), index=df.index, dtype="float64")


def add_elapsed_seconds(df, group_columns):
    df["_sort_ts_seconds"] = timestamp_to_seconds(df)

    existing_group_columns = [col for col in parse_columns(group_columns) if col in df.columns]

    if existing_group_columns:
        df["elapsed_seconds"] = df.groupby(existing_group_columns, dropna=False)[
            "_sort_ts_seconds"
        ].transform(lambda s: s - s.min())
    else:
        df["elapsed_seconds"] = df["_sort_ts_seconds"] - df["_sort_ts_seconds"].min()

    df["elapsed_seconds"] = pd.to_numeric(df["elapsed_seconds"], errors="coerce")
    return df, existing_group_columns


def add_slo_violation(
    df,
    latency_column,
    error_rate_column,
    latency_threshold,
    error_rate_threshold,
    slo_mode,
):
    latency_condition = pd.Series(False, index=df.index)
    error_condition = pd.Series(False, index=df.index)

    if latency_column in df.columns and latency_threshold is not None:
        df[latency_column] = pd.to_numeric(df[latency_column], errors="coerce")
        latency_condition = df[latency_column] > latency_threshold

    if error_rate_column in df.columns and error_rate_threshold is not None:
        df[error_rate_column] = pd.to_numeric(df[error_rate_column], errors="coerce")
        error_condition = df[error_rate_column] > error_rate_threshold

    if slo_mode == "latency":
        violation = latency_condition
    elif slo_mode == "error":
        violation = error_condition
    elif slo_mode == "latency_and_error":
        violation = latency_condition & error_condition
    else:  # latency_or_error
        violation = latency_condition | error_condition

    df["slo_violation"] = violation.astype(int)
    return df



def mark_idle_training_rows(df, rps_threshold, in_progress_threshold):
    """Mark clean idle rows that can teach the model to return to min pods.

    We intentionally do not trust desired_replicas for idle rows because HPA/KEDA
    may still be in the middle of scale-down. For these rows the thesis target
    is the minimum pod count, not the currently observed replica state.
    """
    scenario_idle = pd.Series(False, index=df.index)
    if "scenario" in df.columns:
        scenario_idle = df["scenario"].astype(str).str.lower().eq("idle")

    low_rps = pd.Series(False, index=df.index)
    if "rps" in df.columns:
        low_rps = pd.to_numeric(df["rps"], errors="coerce").fillna(0) <= rps_threshold

    low_inflight = pd.Series(True, index=df.index)
    if "in_progress_requests" in df.columns:
        low_inflight = pd.to_numeric(df["in_progress_requests"], errors="coerce").fillna(0) <= in_progress_threshold

    df["is_idle_training_row"] = ((scenario_idle | low_rps) & low_inflight).astype(int)
    return df


def downsample_idle_rows(dataset, max_idle_ratio, random_state):
    """Limit idle rows so they do not dominate the training data."""
    if "is_idle_training_row" not in dataset.columns or max_idle_ratio is None:
        return dataset, 0

    if max_idle_ratio <= 0 or max_idle_ratio >= 1:
        return dataset, 0

    idle_mask = dataset["is_idle_training_row"].astype(int).eq(1)
    idle_df = dataset[idle_mask]
    non_idle_df = dataset[~idle_mask]

    if idle_df.empty or non_idle_df.empty:
        return dataset, 0

    max_idle_count = int(len(non_idle_df) * max_idle_ratio / (1 - max_idle_ratio))
    if len(idle_df) <= max_idle_count:
        return dataset, 0

    sampled_idle = idle_df.sample(n=max_idle_count, random_state=random_state).sort_index()
    reduced = pd.concat([non_idle_df, sampled_idle], axis=0).sort_index().reset_index(drop=True)
    return reduced, len(idle_df) - len(sampled_idle)


# -------------------------
# Main
# -------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clean exported Prometheus/Kubernetes metrics and split them into train/test CSV files "
            "for ML-based pod count prediction. The script also derives thesis-friendly columns: "
            "current_pods, desired_replicas, slo_violation, elapsed_seconds."
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
        help="Scenario to use for ML training. Default: step-load. Use 'all' to include all scenarios; idle rows are included only when --include-idle is set.",
    )
    parser.add_argument(
        "--include-idle",
        action="store_true",
        help=(
            "Include clean idle rows in the dataset. For idle rows, required_pods is "
            "overridden to --idle-target-pods so the model can learn to scale down."
        ),
    )
    parser.add_argument(
        "--idle-target-pods",
        type=int,
        default=1,
        help="Target pod count assigned to clean idle rows. Default: 1",
    )
    parser.add_argument(
        "--idle-rps-threshold",
        type=float,
        default=0.5,
        help="Rows with rps <= this value can be treated as idle. Default: 0.5",
    )
    parser.add_argument(
        "--idle-in-progress-threshold",
        type=float,
        default=0.5,
        help="Rows with in_progress_requests <= this value can be treated as idle. Default: 0.5",
    )
    parser.add_argument(
        "--max-idle-ratio",
        type=float,
        default=0.25,
        help=(
            "Maximum fraction of idle rows in the final clean dataset. "
            "Default: 0.25. Use 0 or >=1 to disable downsampling."
        ),
    )

    parser.add_argument(
        "--autoscalers",
        default="",
        help=(
            "Optional comma-separated autoscaler filter, e.g. HPA,KEDA. "
            "When --include-idle is set, rows with scenario=idle are kept as idle examples."
        ),
    )

    parser.add_argument(
        "--target-column",
        default="auto",
        help="Target column to predict. Use 'auto' to detect required_pods or desired_replicas. Default: auto",
    )
    parser.add_argument(
        "--features",
        default=",".join(DEFAULT_FEATURE_COLUMNS),
        help="Comma-separated ML feature columns. Default: rps,p95_latency,error_rate,cpu_mcores,in_progress_requests",
    )
    parser.add_argument(
        "--current-pods-column",
        default=",".join(DEFAULT_CURRENT_PODS_CANDIDATES),
        help=(
            "Comma-separated source column candidates for current_pods. "
            "Default: current_pods,pod_count,running_pods,ready_replicas,available_replicas"
        ),
    )
    parser.add_argument(
        "--include-current-pods-feature",
        action="store_true",
        help=(
            "Include current_pods as an input feature. Default is false because current pod count "
            "can make the target too dependent on replica state."
        ),
    )
    # Backward-compatible alias from the previous script.
    parser.add_argument(
        "--include-pod-count-feature",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--split-method",
        choices=["time", "random", "set", "target_vus"],
        default="set",
        help=(
            "Train/test split method. "
            "'set' is recommended for the thesis: train on earlier repetitions and test on a held-out set. "
            "Default: set"
        ),
    )
    parser.add_argument(
        "--test-set-nos",
        default="",
        help=(
            "Comma-separated set_no values for the test dataset when --split-method set is used. "
            "Default: the maximum set_no in the data, for example 5."
        ),
    )
    parser.add_argument(
        "--test-target-vus",
        default="",
        help=(
            "Comma-separated target_vus values for the test dataset when --split-method target_vus is used. "
            "Default: the maximum target_vus in the data, for example 400."
        ),
    )
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--min-rps",
        type=float,
        default=0.0,
        help="Minimum RPS to keep. Default 0.0 keeps all non-idle rows with valid RPS.",
    )

    # SLO settings. Adjust these according to your thesis definition.
    parser.add_argument(
        "--latency-slo-threshold",
        type=float,
        default=0.5,
        help=(
            "p95 latency SLO threshold. Default: 0.5. "
            "If p95_latency is in seconds this means 500 ms; if it is in ms, pass 500."
        ),
    )
    parser.add_argument(
        "--error-rate-slo-threshold",
        type=float,
        default=0.05,
        help="Error-rate SLO threshold. Default: 0.05 means 5% if error_rate is a ratio.",
    )
    parser.add_argument(
        "--slo-mode",
        choices=["latency_or_error", "latency", "error", "latency_and_error"],
        default="latency_or_error",
        help="How to calculate slo_violation. Default: latency_or_error",
    )
    parser.add_argument("--latency-column", default="p95_latency")
    parser.add_argument("--error-rate-column", default="error_rate")
    parser.add_argument(
        "--elapsed-group-cols",
        default=",".join(DEFAULT_ELAPSED_GROUP_COLUMNS),
        help=(
            "Columns used to reset elapsed_seconds per experiment run. "
            "Default: run_id,autoscaler,scenario,set_no,target_vus,baseline_vus,spike_target_vus"
        ),
    )

    args = parser.parse_args()

    if not 0 < args.test_size < 1:
        raise ValueError("--test-size must be between 0 and 1, e.g. 0.2")

    df_raw = pd.read_csv(args.input)
    raw_rows = len(df_raw)

    df = df_raw.copy()

    # 1. Scenario filtering.
    # By default idle rows are removed. If --include-idle is used, clean idle rows
    # are kept and later relabeled to idle-target-pods.
    if "scenario" in df.columns:
        if args.scenario != "all":
            if args.include_idle:
                df = df[(df["scenario"] == args.scenario) | (df["scenario"] == "idle")].copy()
            else:
                df = df[df["scenario"] == args.scenario].copy()
        elif not args.include_idle:
            df = df[df["scenario"] != "idle"].copy()

    if args.autoscalers and "autoscaler" in df.columns:
        allowed_autoscalers = parse_columns(args.autoscalers)
        autoscaler_mask = df["autoscaler"].isin(allowed_autoscalers)
        if args.include_idle and "scenario" in df.columns:
            autoscaler_mask = autoscaler_mask | df["scenario"].astype(str).str.lower().eq("idle")
        df = df[autoscaler_mask].copy()

    if df.empty:
        raise ValueError("No rows left after scenario/autoscaler filtering. Check --scenario and --autoscalers values.")

    # 2. Normalize/derive thesis-friendly columns.
    target_input_column = resolve_target_column(df, args.target_column)

    df, current_pods_source = add_current_pods_column(df, args.current_pods_column)
    df, desired_replicas_source = add_desired_replicas_column(df, target_input_column)
    df = add_slo_violation(
        df=df,
        latency_column=args.latency_column,
        error_rate_column=args.error_rate_column,
        latency_threshold=args.latency_slo_threshold,
        error_rate_threshold=args.error_rate_slo_threshold,
        slo_mode=args.slo_mode,
    )
    df, elapsed_group_columns = add_elapsed_seconds(df, args.elapsed_group_cols)

    # 3. Select features and target.
    feature_columns = parse_columns(args.features)

    if args.include_current_pods_feature or args.include_pod_count_feature:
        if "current_pods" not in feature_columns:
            feature_columns.append("current_pods")

    # Keep a stable thesis target name.
    if target_input_column != "required_pods":
        df["required_pods"] = pd.to_numeric(df[target_input_column], errors="coerce")
    else:
        df["required_pods"] = pd.to_numeric(df["required_pods"], errors="coerce")

    target_column = "required_pods"
    df["target_source"] = target_input_column

    required_columns = feature_columns + [target_column]

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Missing required columns in input CSV after derivation: " + ", ".join(missing_columns)
        )

    # Metadata columns are kept for traceability but should not be used as model features unless explicitly selected.
    metadata_columns = [
        "timestamp",
        "datetime_utc",
        "elapsed_seconds",
        "run_id",
        "scenario",
        "autoscaler",
        "set_no",
        "target_vus",
        "baseline_vus",
        "spike_target_vus",
        "current_pods",
        "desired_replicas",
        "slo_violation",
        "is_idle_training_row",
        "target_source",
    ]
    metadata_columns = [col for col in metadata_columns if col in df.columns]

    numeric_columns = list(
        dict.fromkeys(
            required_columns
            + [
                "rps",
                "p95_latency",
                "error_rate",
                "cpu_mcores",
                "in_progress_requests",
                "elapsed_seconds",
                "current_pods",
                "desired_replicas",
                "slo_violation",
            ]
        )
    )
    df = ensure_numeric(df, numeric_columns)

    idle_overridden_count = 0
    if args.include_idle:
        df = mark_idle_training_rows(
            df,
            rps_threshold=args.idle_rps_threshold,
            in_progress_threshold=args.idle_in_progress_threshold,
        )
        idle_mask = df["is_idle_training_row"].astype(int).eq(1)
        idle_overridden_count = int(idle_mask.sum())
        df.loc[idle_mask, target_column] = args.idle_target_pods
        df.loc[idle_mask, "desired_replicas"] = args.idle_target_pods
        df.loc[idle_mask, "target_source"] = "idle_rule_min_pods"
    else:
        df["is_idle_training_row"] = 0

    # 4. Clean invalid or empty rows.
    # Only feature + target columns are mandatory. current_pods may be empty when it was not exported.
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
    if target_column in df.columns:
        df = df[df[target_column] >= 1]

    # 5. Sort chronologically.
    # Important: do not sort by run_id/set_no before a time split. Global timestamp order
    # preserves the actual experiment order.
    if "_sort_ts_seconds" in df.columns:
        df = df.sort_values("_sort_ts_seconds").reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    output_columns = metadata_columns + feature_columns + [target_column]
    output_columns = list(dict.fromkeys(output_columns))

    dataset = df[output_columns].copy()

    idle_dropped_count = 0
    if args.include_idle:
        dataset, idle_dropped_count = downsample_idle_rows(
            dataset,
            max_idle_ratio=args.max_idle_ratio,
            random_state=args.random_state,
        )

    if len(dataset) < 2:
        raise ValueError("Not enough rows after cleaning to split train/test dataset")

    # 6. Split train/test.
    split_detail = ""

    if args.split_method == "random":
        dataset_for_split = dataset.sample(frac=1, random_state=args.random_state).reset_index(drop=True)
        split_index = int(len(dataset_for_split) * (1 - args.test_size))
        train_df = dataset_for_split.iloc[:split_index].copy()
        test_df = dataset_for_split.iloc[split_index:].copy()
        split_detail = f"random {1 - args.test_size:.0%}/{args.test_size:.0%}"

    elif args.split_method == "time":
        dataset_for_split = dataset
        split_index = int(len(dataset_for_split) * (1 - args.test_size))
        train_df = dataset_for_split.iloc[:split_index].copy()
        test_df = dataset_for_split.iloc[split_index:].copy()
        split_detail = f"chronological first {1 - args.test_size:.0%} train, last {args.test_size:.0%} test"

    elif args.split_method == "set":
        if "set_no" not in dataset.columns:
            raise ValueError("--split-method set requires a set_no column in the input CSV.")

        dataset["set_no"] = pd.to_numeric(dataset["set_no"], errors="coerce")
        available_sets = sorted(dataset["set_no"].dropna().unique().tolist())
        # set_no=0 is normally idle/metadata and should not become the default test set.
        candidate_test_sets = [s for s in available_sets if s > 0]
        if not candidate_test_sets:
            raise ValueError("No valid positive set_no values were found for set-based split.")

        test_sets = parse_number_list(args.test_set_nos)
        if not test_sets:
            test_sets = [max(candidate_test_sets)]

        train_df = dataset[~dataset["set_no"].isin(test_sets)].copy()
        test_df = dataset[dataset["set_no"].isin(test_sets)].copy()
        split_detail = f"train sets except [{format_number_list(test_sets)}], test sets [{format_number_list(test_sets)}]"

    elif args.split_method == "target_vus":
        if "target_vus" not in dataset.columns:
            raise ValueError("--split-method target_vus requires a target_vus column in the input CSV.")

        dataset["target_vus"] = pd.to_numeric(dataset["target_vus"], errors="coerce")
        available_targets = sorted(dataset["target_vus"].dropna().unique().tolist())
        if not available_targets:
            raise ValueError("No valid target_vus values were found for target_vus-based split.")

        test_targets = parse_number_list(args.test_target_vus)
        if not test_targets:
            test_targets = [max(available_targets)]

        train_df = dataset[~dataset["target_vus"].isin(test_targets)].copy()
        test_df = dataset[dataset["target_vus"].isin(test_targets)].copy()
        split_detail = f"train target_vus except [{format_number_list(test_targets)}], test target_vus [{format_number_list(test_targets)}]"

    if train_df.empty or test_df.empty:
        raise ValueError(
            f"Train or test dataset is empty after split. "
            f"split_method={args.split_method}, detail={split_detail}. "
            "Check --test-set-nos, --test-target-vus, or --scenario."
        )

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
    print(f"Autoscaler filter: {args.autoscalers or 'all'}")
    print(f"Include idle rows: {args.include_idle}")
    if args.include_idle:
        print(f"Idle target pods: {args.idle_target_pods}")
        print(f"Idle rows relabeled before downsampling: {idle_overridden_count}")
        print(f"Idle rows dropped by downsampling: {idle_dropped_count}")
    print(f"Split method: {args.split_method}")
    print(f"Split detail: {split_detail}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")

    distribution_columns = [col for col in ["scenario", "autoscaler", "set_no", "target_vus"] if col in dataset.columns]
    if distribution_columns:
        print("\nTrain distribution:")
        print(train_df.groupby(distribution_columns).size().to_string())
        print("\nTest distribution:")
        print(test_df.groupby(distribution_columns).size().to_string())
        print("")
    print(f"Features: {', '.join(feature_columns)}")
    print(f"Target: {target_column} (source: {target_input_column})")
    print(f"current_pods source: {current_pods_source or 'NOT FOUND'}")
    print(f"desired_replicas source: {desired_replicas_source}")
    print(f"elapsed_seconds group columns: {', '.join(elapsed_group_columns) if elapsed_group_columns else 'global'}")
    print(
        "SLO: "
        f"mode={args.slo_mode}, "
        f"latency>{args.latency_slo_threshold}, "
        f"error_rate>{args.error_rate_slo_threshold}"
    )
    print(f"Clean file: {args.clean_output}")
    print(f"Train file: {args.train_output}")
    print(f"Test file: {args.test_output}")


if __name__ == "__main__":
    main()
