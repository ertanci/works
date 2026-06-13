import argparse
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


DEFAULT_FEATURE_COLUMNS = [
    "rps",
    "p95_latency",
    "error_rate",
    "cpu_mcores",
    "in_progress_requests",
]

DEFAULT_TARGET_COLUMN = "required_pods"

METADATA_COLUMNS = [
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
]


def parse_columns(value):
    if not value:
        return []
    return [col.strip() for col in value.split(",") if col.strip()]


def ensure_required_columns(df, columns, dataset_name):
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise ValueError(
            f"{dataset_name} dataset is missing required columns: {', '.join(missing)}"
        )


def prepare_dataset(df, feature_columns, target_column, dataset_name):
    required_columns = feature_columns + [target_column]
    ensure_required_columns(df, required_columns, dataset_name)

    prepared = df.copy()

    for col in required_columns:
        prepared[col] = pd.to_numeric(prepared[col], errors="coerce")

    before = len(prepared)
    prepared = prepared.dropna(subset=required_columns).copy()
    dropped = before - len(prepared)

    if dropped:
        print(f"WARNING: dropped {dropped} rows from {dataset_name} due to NA values.")

    # Pod count target must be positive.
    prepared = prepared[prepared[target_column] >= 1].copy()

    return prepared


def build_models(random_state):
    return {
        "linear_regression": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("model", LinearRegression()),
            ]
        ),
        "svr": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("model", SVR(kernel="rbf", C=10, epsilon=0.1)),
            ]
        ),
        "mlp": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPRegressor(
                        hidden_layer_sizes=(64, 32),
                        activation="relu",
                        solver="adam",
                        max_iter=1000,
                        random_state=random_state,
                        early_stopping=True,
                        n_iter_no_change=30,
                    ),
                ),
            ]
        ),
    }


def pod_round(values, method, min_pods, max_pods):
    values = np.asarray(values, dtype=float)

    if method == "ceil":
        rounded = np.ceil(values)
    elif method == "floor":
        rounded = np.floor(values)
    else:
        rounded = np.rint(values)

    rounded = np.clip(rounded, min_pods, max_pods)

    return rounded.astype(int)


def safe_r2(y_true, y_pred):
    try:
        return r2_score(y_true, y_pred)
    except Exception:
        return float("nan")


def evaluate_predictions(model_name, y_true, raw_predictions, pod_predictions):
    y_true = np.asarray(y_true, dtype=float)
    raw_predictions = np.asarray(raw_predictions, dtype=float)
    pod_predictions = np.asarray(pod_predictions, dtype=float)

    errors = pod_predictions - y_true
    abs_errors = np.abs(errors)

    raw_mse = mean_squared_error(y_true, raw_predictions)
    pod_mse = mean_squared_error(y_true, pod_predictions)

    return {
        "model": model_name,

        # Regression metrics on raw floating predictions.
        "mae_raw": mean_absolute_error(y_true, raw_predictions),
        "rmse_raw": math.sqrt(raw_mse),
        "r2_raw": safe_r2(y_true, raw_predictions),

        # Autoscaling-friendly metrics on integer pod predictions.
        "mae": mean_absolute_error(y_true, pod_predictions),
        "rmse": math.sqrt(pod_mse),
        "mse": pod_mse,
        "r2": safe_r2(y_true, pod_predictions),

        "exact_match_rate": float(np.mean(pod_predictions == y_true)),
        "within_1_pod_rate": float(np.mean(abs_errors <= 1)),
        "under_prediction_rate": float(np.mean(pod_predictions < y_true)),
        "over_prediction_rate": float(np.mean(pod_predictions > y_true)),
        "avg_actual_pods": float(np.mean(y_true)),
        "avg_predicted_pods": float(np.mean(pod_predictions)),
        "max_actual_pods": float(np.max(y_true)),
        "max_predicted_pods": float(np.max(pod_predictions)),
    }


def build_prediction_rows(model_name, test_df, feature_columns, target_column, raw_predictions, pod_predictions):
    metadata_columns = [col for col in METADATA_COLUMNS if col in test_df.columns]
    output = test_df[metadata_columns + feature_columns].copy()
    output.insert(0, "row_id", test_df.index)
    output["model"] = model_name
    output["actual_required_pods"] = test_df[target_column].astype(int).values
    output["predicted_pods_raw"] = raw_predictions
    output["predicted_pods"] = pod_predictions
    output["prediction_error"] = output["predicted_pods"] - output["actual_required_pods"]
    output["abs_error"] = output["prediction_error"].abs()
    output["under_predicted"] = output["predicted_pods"] < output["actual_required_pods"]
    output["over_predicted"] = output["predicted_pods"] > output["actual_required_pods"]
    return output


def build_group_metrics(predictions_df):
    group_cols = [
        col
        for col in ["model", "scenario", "autoscaler", "target_vus", "set_no"]
        if col in predictions_df.columns
    ]

    if not group_cols:
        return pd.DataFrame()

    rows = []
    for keys, group in predictions_df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)

        actual = group["actual_required_pods"].astype(float).values
        pred = group["predicted_pods"].astype(float).values
        abs_error = np.abs(pred - actual)

        row = dict(zip(group_cols, keys))
        row.update(
            {
                "rows": len(group),
                "mae": mean_absolute_error(actual, pred),
                "rmse": math.sqrt(mean_squared_error(actual, pred)),
                "exact_match_rate": float(np.mean(pred == actual)),
                "within_1_pod_rate": float(np.mean(abs_error <= 1)),
                "under_prediction_rate": float(np.mean(pred < actual)),
                "over_prediction_rate": float(np.mean(pred > actual)),
                "avg_actual_pods": float(np.mean(actual)),
                "avg_predicted_pods": float(np.mean(pred)),
            }
        )
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate ML-based Kubernetes autoscaling models")

    parser.add_argument("--train", default="results/metrics/ml_train_all.csv")
    parser.add_argument("--test", default="results/metrics/ml_test_all.csv")

    parser.add_argument(
        "--features",
        default=",".join(DEFAULT_FEATURE_COLUMNS),
        help=(
            "Comma-separated model input columns. Default excludes current_pods, "
            "desired_replicas and slo_violation to avoid leakage."
        ),
    )
    parser.add_argument("--target-column", default=DEFAULT_TARGET_COLUMN)

    parser.add_argument("--model-output", default="models/best_model.joblib")
    parser.add_argument(
        "--models-output-dir",
        default="models",
        help="Directory where each trained model artifact is saved separately.",
    )
    parser.add_argument("--results-output", default="results/metrics/model_results.csv")
    parser.add_argument("--predictions-output", default="results/metrics/model_predictions.csv")
    parser.add_argument("--group-results-output", default="results/metrics/model_group_results.csv")

    parser.add_argument("--rounding", choices=["round", "ceil", "floor"], default="ceil")
    parser.add_argument("--min-pods", type=int, default=1)
    parser.add_argument(
        "--max-pods",
        type=int,
        default=None,
        help="Maximum allowed pod count. If omitted, the max target value in train/test is used.",
    )
    parser.add_argument("--random-state", type=int, default=42)

    args = parser.parse_args()

    feature_columns = parse_columns(args.features)
    target_column = args.target_column

    leakage_columns = {"current_pods", "desired_replicas", "required_pods", "slo_violation"}
    risky_features = leakage_columns.intersection(feature_columns)
    if risky_features:
        print(
            "WARNING: These features may cause target leakage or duplicate target logic: "
            + ", ".join(sorted(risky_features))
        )

    train_df = pd.read_csv(args.train)
    test_df = pd.read_csv(args.test)

    train_df = prepare_dataset(train_df, feature_columns, target_column, "train")
    test_df = prepare_dataset(test_df, feature_columns, target_column, "test")

    if len(train_df) == 0 or len(test_df) == 0:
        raise ValueError("Train or test dataset is empty after cleaning.")

    max_pods = args.max_pods
    if max_pods is None:
        max_pods = int(max(train_df[target_column].max(), test_df[target_column].max()))

    x_train = train_df[feature_columns]
    y_train = train_df[target_column].astype(float)

    x_test = test_df[feature_columns]
    y_test = test_df[target_column].astype(float)

    models = build_models(args.random_state)

    results = []
    prediction_outputs = []
    trained_models = {}

    print("Training configuration")
    print(f"Train file: {args.train} | rows={len(train_df)}")
    print(f"Test file:  {args.test} | rows={len(test_df)}")
    print(f"Features: {', '.join(feature_columns)}")
    print(f"Target: {target_column}")
    print(f"Rounding: {args.rounding}")
    print(f"Pod clipping range: [{args.min_pods}, {max_pods}]")
    print("")

    for name, model in models.items():
        print(f"Training {name}...")
        model.fit(x_train, y_train)

        raw_predictions = model.predict(x_test)
        pod_predictions = pod_round(raw_predictions, args.rounding, args.min_pods, max_pods)

        metrics = evaluate_predictions(name, y_test, raw_predictions, pod_predictions)
        results.append(metrics)
        trained_models[name] = model

        prediction_outputs.append(
            build_prediction_rows(
                name,
                test_df,
                feature_columns,
                target_column,
                raw_predictions,
                pod_predictions,
            )
        )

        print(metrics)

    results_df = pd.DataFrame(results).sort_values(["mae", "rmse", "under_prediction_rate"]).reset_index(drop=True)
    predictions_df = pd.concat(prediction_outputs, ignore_index=True)
    group_results_df = build_group_metrics(predictions_df)

    Path(args.results_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.predictions_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.group_results_output).parent.mkdir(parents=True, exist_ok=True)

    results_df.to_csv(args.results_output, index=False)
    predictions_df.to_csv(args.predictions_output, index=False)
    group_results_df.to_csv(args.group_results_output, index=False)

    best_model_name = results_df.iloc[0]["model"]
    best_model = trained_models[best_model_name]

    Path(args.model_output).parent.mkdir(parents=True, exist_ok=True)
    models_output_dir = Path(args.models_output_dir)
    models_output_dir.mkdir(parents=True, exist_ok=True)

    model_artifacts = {}
    for model_name, model in trained_models.items():
        model_result = results_df[results_df["model"] == model_name].to_dict(orient="records")
        artifact = {
            "model_name": model_name,
            "model": model,
            "features": feature_columns,
            "target": target_column,
            "rounding": args.rounding,
            "min_pods": args.min_pods,
            "max_pods": max_pods,
            "results": results_df.to_dict(orient="records"),
            "model_result": model_result[0] if model_result else None,
        }
        artifact_path = models_output_dir / f"{model_name}_model.joblib"
        joblib.dump(artifact, artifact_path)
        model_artifacts[model_name] = str(artifact_path)

    joblib.dump(
        {
            "model_name": best_model_name,
            "model": best_model,
            "features": feature_columns,
            "target": target_column,
            "rounding": args.rounding,
            "min_pods": args.min_pods,
            "max_pods": max_pods,
            "results": results_df.to_dict(orient="records"),
            "model_artifacts": model_artifacts,
        },
        args.model_output,
    )

    print("\nTraining completed.")
    print(f"Best model: {best_model_name}")
    print(f"Results saved to: {args.results_output}")
    print(f"Predictions saved to: {args.predictions_output}")
    print(f"Group results saved to: {args.group_results_output}")
    print(f"Best model saved to: {args.model_output}")
    print(f"Individual models saved to: {models_output_dir}")
    for model_name, artifact_path in model_artifacts.items():
        print(f"  {model_name}: {artifact_path}")


if __name__ == "__main__":
    main()
