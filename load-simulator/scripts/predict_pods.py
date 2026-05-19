import argparse
import json
import math
from pathlib import Path

import joblib
import pandas as pd


DEFAULT_FEATURES = [
    "rps",
    "p95_latency",
    "error_rate",
    "cpu_mcores",
    "in_progress_requests",
]


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


def load_artifact(path: str):
    artifact = joblib.load(path)
    if not isinstance(artifact, dict):
        raise ValueError("Model artifact must be a dictionary created by train_model_v2.py")
    if "model" not in artifact or "features" not in artifact:
        raise ValueError("Model artifact must contain 'model' and 'features' keys")
    return artifact


def build_input(args, features):
    values = {
        "rps": args.rps,
        "p95_latency": args.p95_latency,
        "error_rate": args.error_rate,
        "cpu_mcores": args.cpu_mcores,
        "in_progress_requests": args.in_progress_requests,
    }

    missing = [feature for feature in features if feature not in values]
    if missing:
        raise ValueError(
            "The model expects features that this script cannot provide: "
            + ", ".join(missing)
        )

    return pd.DataFrame([{feature: values[feature] for feature in features}])


def main():
    parser = argparse.ArgumentParser(
        description="Predict required pod count from manually supplied metrics"
    )

    parser.add_argument("--model", default="models/best_model.joblib")

    parser.add_argument("--rps", type=float, required=True)
    parser.add_argument("--p95-latency", type=float, required=True, help="p95 latency in seconds")
    parser.add_argument("--error-rate", type=float, required=True, help="error ratio, e.g. 0.01 for 1%")
    parser.add_argument("--cpu-mcores", type=float, required=True)
    parser.add_argument("--in-progress-requests", type=float, required=True)

    parser.add_argument("--min-pods", type=int, default=1)
    parser.add_argument("--max-pods", type=int, default=60)
    parser.add_argument(
        "--rounding",
        choices=["ceil", "round", "floor"],
        default="ceil",
        help="ceil is safer for autoscaling because it avoids under-provisioning",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to save the prediction result as JSON",
    )

    args = parser.parse_args()

    if args.min_pods < 1:
        raise ValueError("--min-pods must be at least 1")
    if args.max_pods < args.min_pods:
        raise ValueError("--max-pods must be greater than or equal to --min-pods")

    artifact = load_artifact(args.model)
    model = artifact["model"]
    features = artifact.get("features", DEFAULT_FEATURES)

    input_data = build_input(args, features)
    raw_prediction = float(model.predict(input_data)[0])
    predicted_pods = clamp(round_pods(raw_prediction, args.rounding), args.min_pods, args.max_pods)

    result = {
        "model_name": artifact.get("model_name", "unknown"),
        "features": features,
        "input": input_data.iloc[0].to_dict(),
        "raw_prediction": raw_prediction,
        "recommended_pods": predicted_pods,
        "rounding": args.rounding,
        "min_pods": args.min_pods,
        "max_pods": args.max_pods,
    }

    print("Prediction completed.")
    print(f"Model: {result['model_name']}")
    print(f"Raw prediction: {raw_prediction:.3f}")
    print(f"Recommended pod count: {predicted_pods}")

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"JSON saved to: {output_path}")


if __name__ == "__main__":
    main()
