import argparse
import math
import joblib
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description="Predict required pod count")

    parser.add_argument("--model", default="models/best_model.joblib")

    parser.add_argument("--rps", type=float, required=True)
    parser.add_argument("--p95-latency", type=float, required=True)
    parser.add_argument("--error-rate", type=float, required=True)
    parser.add_argument("--cpu-mcores", type=float, required=True)
    parser.add_argument("--in-progress-requests", type=float, required=True)

    parser.add_argument("--min-pods", type=int, default=1)
    parser.add_argument("--max-pods", type=int, default=10)

    args = parser.parse_args()

    artifact = joblib.load(args.model)

    model = artifact["model"]
    features = artifact["features"]

    input_data = pd.DataFrame(
        [
            {
                "rps": args.rps,
                "p95_latency": args.p95_latency,
                "error_rate": args.error_rate,
                "cpu_mcores": args.cpu_mcores,
                "in_progress_requests": args.in_progress_requests,
            }
        ]
    )

    input_data = input_data[features]

    raw_prediction = model.predict(input_data)[0]

    predicted_pods = math.ceil(raw_prediction)
    predicted_pods = max(args.min_pods, min(args.max_pods, predicted_pods))

    print("Prediction completed.")
    print(f"Model: {artifact['model_name']}")
    print(f"Raw prediction: {raw_prediction:.3f}")
    print(f"Recommended pod count: {predicted_pods}")


if __name__ == "__main__":
    main()