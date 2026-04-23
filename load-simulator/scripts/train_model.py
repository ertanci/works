import argparse
from pathlib import Path
import joblib

import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


FEATURE_COLUMNS = [
    "rps",
    "p95_latency",
    "error_rate",
    "cpu_mcores",
    "in_progress_requests",
]

TARGET_COLUMN = "target_pod_count"


def evaluate_model(name, model, x_test, y_test):
    predictions = model.predict(x_test)

    # Pod sayısı tam sayı olmalı
    rounded_predictions = predictions.round().clip(min=1)

    mae = mean_absolute_error(y_test, rounded_predictions)
    mse = mean_squared_error(y_test, rounded_predictions)
    r2 = r2_score(y_test, rounded_predictions)

    return {
        "model": name,
        "mae": mae,
        "mse": mse,
        "r2": r2,
    }


def main():
    parser = argparse.ArgumentParser(description="Train ML autoscaling models")
    parser.add_argument("--train", default="data/processed/train.csv")
    parser.add_argument("--test", default="data/processed/test.csv")
    parser.add_argument("--model-output", default="models/best_model.joblib")
    parser.add_argument("--results-output", default="data/processed/model_results.csv")

    args = parser.parse_args()

    train_df = pd.read_csv(args.train)
    test_df = pd.read_csv(args.test)

    x_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN]

    x_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_COLUMN]

    models = {
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
                        random_state=42,
                    ),
                ),
            ]
        ),
    }

    results = []
    trained_models = {}

    for name, model in models.items():
        print(f"Training {name}...")
        model.fit(x_train, y_train)

        metrics = evaluate_model(name, model, x_test, y_test)
        results.append(metrics)
        trained_models[name] = model

        print(metrics)

    results_df = pd.DataFrame(results).sort_values("mae")

    Path(args.results_output).parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(args.results_output, index=False)

    best_model_name = results_df.iloc[0]["model"]
    best_model = trained_models[best_model_name]

    Path(args.model_output).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model_name": best_model_name,
            "model": best_model,
            "features": FEATURE_COLUMNS,
            "target": TARGET_COLUMN,
            "results": results_df.to_dict(orient="records"),
        },
        args.model_output,
    )

    print("\nTraining completed.")
    print(f"Best model: {best_model_name}")
    print(f"Results saved to: {args.results_output}")
    print(f"Best model saved to: {args.model_output}")


if __name__ == "__main__":
    main()