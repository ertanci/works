#!/bin/bash

set -euo pipefail

# ============================================================
# ML Autoscaling Experiment Runner
#
# Runs both step-load and spike-load experiments using the ML
# autoscaler script. Intended to be comparable with the existing
# HPA/KEDA experiment runners.
#
# Default test mode:
#   SETS=1
#
# Final thesis run suggestion:
#   SETS=5
#
# Important:
#   - HPA and KEDA must be deleted before ML autoscaler starts.
#   - Prometheus port-forward must already be running.
#   - The application service/port-forward must already be reachable.
# ============================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="$ROOT_DIR/../results/metrics"
TIMELINE_FILE="$DATA_DIR/experiment_timeline.csv"
mkdir -p "$DATA_DIR"

APP_NAME="${APP_NAME:-autoscale-test-service}"
NAMESPACE="${NAMESPACE:-default}"

STEP_LOAD_SCRIPT="${STEP_LOAD_SCRIPT:-$ROOT_DIR/../k6/common-load-test.js}"
SPIKE_LOAD_SCRIPT="${SPIKE_LOAD_SCRIPT:-$ROOT_DIR/../k6/spike-load-test.js}"
ML_SCRIPT="${ML_SCRIPT:-$ROOT_DIR/predict_live.py}"
MODEL_FILE="${MODEL_FILE:-$ROOT_DIR/../models/best_model.joblib}"

SERVICE_URL="${SERVICE_URL:-http://localhost:3001/health}"
TARGET_URL="${URL:-http://localhost:3001}"
PROM_URL="${PROM_URL:-http://127.0.0.1:19090}"

# For quick validation, use SETS=1. For final thesis measurements, use SETS=5.
SETS="${SETS:-1}"
TARGETS="${TARGETS:-50 100 200 400}"

BASELINE_VUS="${BASELINE_VUS:-50}"
SPIKE_TARGET_VUS="${SPIKE_TARGET_VUS:-400}"

INITIAL_STABILIZATION_SECONDS="${INITIAL_STABILIZATION_SECONDS:-60}"
POST_SCALE_DOWN_STABILIZATION_SECONDS="${POST_SCALE_DOWN_STABILIZATION_SECONDS:-60}"

SCALE_DOWN_TIMEOUT_SECONDS="${SCALE_DOWN_TIMEOUT_SECONDS:-900}"
SCALE_DOWN_CHECK_INTERVAL_SECONDS="${SCALE_DOWN_CHECK_INTERVAL_SECONDS:-10}"

DELAY_FACTOR="${DELAY_FACTOR:-1.2}"
CPU_FACTOR="${CPU_FACTOR:-1.2}"
ERROR_FACTOR="${ERROR_FACTOR:-1}"

ML_INTERVAL_SECONDS="${ML_INTERVAL_SECONDS:-5}"
ML_SCALE_UP_COOLDOWN_SECONDS="${ML_SCALE_UP_COOLDOWN_SECONDS:-15}"
ML_SCALE_DOWN_COOLDOWN_SECONDS="${ML_SCALE_DOWN_COOLDOWN_SECONDS:-60}"
ML_MIN_CHANGE="${ML_MIN_CHANGE:-1}"
ML_MIN_PODS="${ML_MIN_PODS:-1}"
ML_MAX_PODS="${ML_MAX_PODS:-60}"
ML_LATENCY_SLO_THRESHOLD="${ML_LATENCY_SLO_THRESHOLD:-0.5}"
ML_ERROR_RATE_SLO_THRESHOLD="${ML_ERROR_RATE_SLO_THRESHOLD:-0.05}"
ML_ENDPOINT_LABEL="${ML_ENDPOINT_LABEL:-exported_endpoint}"
ML_STATUS_LABEL="${ML_STATUS_LABEL:-http_status}"
ML_CONTAINER="${ML_CONTAINER:-ats}"
ML_IDLE_GUARD="${ML_IDLE_GUARD:-true}"
ML_IDLE_RPS_THRESHOLD="${ML_IDLE_RPS_THRESHOLD:-0.5}"
ML_IDLE_IN_PROGRESS_THRESHOLD="${ML_IDLE_IN_PROGRESS_THRESHOLD:-0.5}"
ML_IDLE_CONSECUTIVE_SAMPLES="${ML_IDLE_CONSECUTIVE_SAMPLES:-2}"

EXPERIMENT_DATE="$(date +"%Y%m%d_%H%M%S")"
ML_OUTPUT_CSV="${ML_OUTPUT_CSV:-$DATA_DIR/ml_autoscaler_live_${EXPERIMENT_DATE}.csv}"
ML_LOG_FILE="${ML_LOG_FILE:-$DATA_DIR/ml_autoscaler_live_${EXPERIMENT_DATE}.log}"

ML_PID=""

# If you want ML to behave like HPA/KEDA rate limits, set:
#   ML_HPA_LIKE_POLICY=true
# For the thesis direct-ML autoscaler design, default is false.
ML_HPA_LIKE_POLICY="${ML_HPA_LIKE_POLICY:-false}"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log() {
  echo ""
  echo "[$(timestamp)] $1"
}

init_timeline_file() {
  if [ ! -f "$TIMELINE_FILE" ]; then
    echo "run_id,scenario,autoscaler,set_no,target_vus,baseline_vus,spike_target_vus,start_ts,end_ts" > "$TIMELINE_FILE"
  fi
}

write_timeline_event() {
  run_id="$1"
  scenario="$2"
  autoscaler="$3"
  set_no="$4"
  target_vus="$5"
  baseline_vus="$6"
  spike_target_vus="$7"
  start_ts="$8"
  end_ts="$9"

  echo "${run_id},${scenario},${autoscaler},${set_no},${target_vus},${baseline_vus},${spike_target_vus},${start_ts},${end_ts}" >> "$TIMELINE_FILE"
}

check_required_files() {
  if [ ! -f "$STEP_LOAD_SCRIPT" ]; then
    echo "ERROR: Step load script not found: $STEP_LOAD_SCRIPT"
    exit 1
  fi

  if [ ! -f "$SPIKE_LOAD_SCRIPT" ]; then
    echo "ERROR: Spike load script not found: $SPIKE_LOAD_SCRIPT"
    exit 1
  fi

  if [ ! -f "$ML_SCRIPT" ]; then
    echo "ERROR: ML autoscaler script not found: $ML_SCRIPT"
    exit 1
  fi

  if [ ! -f "$MODEL_FILE" ]; then
    echo "ERROR: ML model file not found: $MODEL_FILE"
    exit 1
  fi
}

check_prometheus() {
  log "Checking Prometheus readiness: $PROM_URL/-/ready"

  if ! curl -sf "$PROM_URL/-/ready" >/dev/null; then
    echo "ERROR: Prometheus is not reachable at $PROM_URL"
    echo "Example port-forward:"
    echo "  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 19090:9090"
    exit 1
  fi

  log "Prometheus is ready"
}

delete_autoscalers() {
  log "Deleting HPA and KEDA ScaledObjects"
  kubectl delete hpa --all -n "$NAMESPACE" || true
  kubectl delete scaledobject --all -n "$NAMESPACE" || true
}

check_app_health() {
  log "Checking app health: $SERVICE_URL"

  for i in $(seq 1 30); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL" || true)

    if [ "$STATUS" = "200" ]; then
      log "App is healthy"
      return 0
    fi

    echo "Waiting for app health... attempt=$i status=$STATUS"
    sleep 2
  done

  echo "ERROR: App did not become healthy"
  exit 1
}

reset_app_to_one_replica() {
  log "Resetting app to 1 replica"

  kubectl scale deployment "$APP_NAME" --replicas=1 -n "$NAMESPACE"
  kubectl rollout restart deployment "$APP_NAME" -n "$NAMESPACE"

  log "Waiting for rollout"
  kubectl rollout status deployment "$APP_NAME" -n "$NAMESPACE"

  check_app_health

  log "Sleeping ${INITIAL_STABILIZATION_SECONDS}s for initial stabilization"
  sleep "$INITIAL_STABILIZATION_SECONDS"
}

get_available_replicas() {
  replicas=$(kubectl get deployment "$APP_NAME" -n "$NAMESPACE" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || true)

  if [ -z "$replicas" ]; then
    echo "0"
  else
    echo "$replicas"
  fi
}

wait_until_scaled_down_to_one() {
  log "Waiting until available replicas return to 1"

  elapsed=0

  while [ "$elapsed" -lt "$SCALE_DOWN_TIMEOUT_SECONDS" ]; do
    # Fail fast if the ML autoscaler process died. Otherwise this loop can wait
    # until timeout while the deployment stays at the last scaled replica count.
    if [ -n "${ML_PID:-}" ] && ! kill -0 "$ML_PID" 2>/dev/null; then
      echo "ERROR: ML autoscaler process stopped while waiting for scale-down."
      echo "ML_PID=$ML_PID"
      echo "Last ML log lines:"
      tail -n 80 "$ML_LOG_FILE" || true
      exit 1
    fi

    replicas=$(get_available_replicas)

    echo "Current available replicas: $replicas | elapsed=${elapsed}s"

    if [ "$replicas" = "1" ]; then
      log "Deployment returned to 1 available replica"
      log "Sleeping ${POST_SCALE_DOWN_STABILIZATION_SECONDS}s after scale-down"
      sleep "$POST_SCALE_DOWN_STABILIZATION_SECONDS"
      return 0
    fi

    sleep "$SCALE_DOWN_CHECK_INTERVAL_SECONDS"
    elapsed=$((elapsed + SCALE_DOWN_CHECK_INTERVAL_SECONDS))
  done

  echo "WARNING: Scale-down timeout reached. Continuing."
  echo "Current available replicas: $(get_available_replicas)"
}

start_ml_autoscaler() {
  if [ -n "${ML_PID:-}" ] && kill -0 "$ML_PID" 2>/dev/null; then
    log "ML autoscaler is already running with PID=$ML_PID"
    return 0
  fi

  log "Starting ML autoscaler"
  log "ML output CSV: $ML_OUTPUT_CSV"
  log "ML log file:   $ML_LOG_FILE"

  policy_arg="--no-hpa-like-policy"
  if [ "$ML_HPA_LIKE_POLICY" = "true" ]; then
    policy_arg="--hpa-like-policy"
  fi

  idle_guard_arg="--idle-guard"
  if [ "$ML_IDLE_GUARD" != "true" ]; then
    idle_guard_arg="--no-idle-guard"
  fi

  python3 "$ML_SCRIPT" \
    --model "$MODEL_FILE" \
    --prom-url "$PROM_URL" \
    --namespace "$NAMESPACE" \
    --deployment "$APP_NAME" \
    --container "$ML_CONTAINER" \
    --endpoint-label "$ML_ENDPOINT_LABEL" \
    --status-label "$ML_STATUS_LABEL" \
    --interval "$ML_INTERVAL_SECONDS" \
    --scale-up-cooldown-seconds "$ML_SCALE_UP_COOLDOWN_SECONDS" \
    --scale-down-cooldown-seconds "$ML_SCALE_DOWN_COOLDOWN_SECONDS" \
    --min-change "$ML_MIN_CHANGE" \
    --min-pods "$ML_MIN_PODS" \
    --max-pods "$ML_MAX_PODS" \
    --latency-slo-threshold "$ML_LATENCY_SLO_THRESHOLD" \
    --error-rate-slo-threshold "$ML_ERROR_RATE_SLO_THRESHOLD" \
    --idle-rps-threshold "$ML_IDLE_RPS_THRESHOLD" \
    --idle-in-progress-threshold "$ML_IDLE_IN_PROGRESS_THRESHOLD" \
    --idle-consecutive-samples "$ML_IDLE_CONSECUTIVE_SAMPLES" \
    $idle_guard_arg \
    $policy_arg \
    --apply-scale \
    --output-csv "$ML_OUTPUT_CSV" \
    > "$ML_LOG_FILE" 2>&1 &

  ML_PID=$!
  log "ML autoscaler started. PID=$ML_PID"

  # Give the monitor time to load the model and collect at least one metric sample.
  sleep "$ML_INTERVAL_SECONDS"
}

stop_ml_autoscaler() {
  if [ -n "${ML_PID:-}" ] && kill -0 "$ML_PID" 2>/dev/null; then
    log "Stopping ML autoscaler. PID=$ML_PID"
    kill "$ML_PID" || true
    wait "$ML_PID" 2>/dev/null || true
  fi
  ML_PID=""
}

cleanup() {
  stop_ml_autoscaler
}

trap cleanup EXIT

run_step_load_test() {
  set_no="$1"
  target_vus="$2"

  log "START ML STEP LOAD | set=${set_no}/${SETS} | target_vus=${target_vus}"

  run_id="$(date +%Y%m%d_%H%M%S)_ML_Set${set_no}_${target_vus}VUs"
  result_dir="$ROOT_DIR/../results/k6/step-load"
  mkdir -p "$result_dir"
  result_file="$result_dir/${run_id}_summary.json"

  start_ts="$(date +%s)"

  URL="$TARGET_URL" \
  TARGET_VUS="$target_vus" \
  DELAY_FACTOR="$DELAY_FACTOR" \
  CPU_FACTOR="$CPU_FACTOR" \
  ERROR_FACTOR="$ERROR_FACTOR" \
  k6 run --summary-export "$result_file" "$STEP_LOAD_SCRIPT"

  end_ts="$(date +%s)"

  write_timeline_event \
    "$run_id" \
    "step-load" \
    "ML" \
    "$set_no" \
    "$target_vus" \
    "0" \
    "0" \
    "$start_ts" \
    "$end_ts"

  log "END ML STEP LOAD | set=${set_no}/${SETS} | target_vus=${target_vus}"
}

run_spike_load_test() {
  set_no="$1"

  log "START ML SPIKE LOAD | set=${set_no}/${SETS} | ${BASELINE_VUS} to ${SPIKE_TARGET_VUS} VUs"

  run_id="$(date +%Y%m%d_%H%M%S)_ML_Spike_Set${set_no}_${BASELINE_VUS}_to_${SPIKE_TARGET_VUS}"
  result_dir="$ROOT_DIR/../results/k6/spike-load"
  mkdir -p "$result_dir"
  result_file="$result_dir/${run_id}_summary.json"

  start_ts="$(date +%s)"

  URL="$TARGET_URL" \
  DELAY_FACTOR="$DELAY_FACTOR" \
  CPU_FACTOR="$CPU_FACTOR" \
  ERROR_FACTOR="$ERROR_FACTOR" \
  BASELINE_VUS="$BASELINE_VUS" \
  SPIKE_TARGET_VUS="$SPIKE_TARGET_VUS" \
  k6 run --summary-export "$result_file" "$SPIKE_LOAD_SCRIPT"

  end_ts="$(date +%s)"

  write_timeline_event \
    "$run_id" \
    "spike" \
    "ML" \
    "$set_no" \
    "$SPIKE_TARGET_VUS" \
    "$BASELINE_VUS" \
    "$SPIKE_TARGET_VUS" \
    "$start_ts" \
    "$end_ts"

  log "END ML SPIKE LOAD | set=${set_no}/${SETS}"
}

run_step_experiments() {
  log "=========================================="
  log "START ML STEP EXPERIMENT"
  log "=========================================="

  delete_autoscalers
  reset_app_to_one_replica
  start_ml_autoscaler

  for set_no in $(seq 1 "$SETS"); do
    log "========== ML STEP | SET ${set_no}/${SETS} =========="

    for target_vus in $TARGETS; do
      run_step_load_test "$set_no" "$target_vus"
      wait_until_scaled_down_to_one
    done
  done

  stop_ml_autoscaler

  log "=========================================="
  log "END ML STEP EXPERIMENT"
  log "=========================================="
}

run_spike_experiments() {
  log "=========================================="
  log "START ML SPIKE EXPERIMENT"
  log "=========================================="

  for set_no in $(seq 1 "$SETS"); do
    log "========== ML SPIKE | SET ${set_no}/${SETS} =========="

    delete_autoscalers
    reset_app_to_one_replica
    start_ml_autoscaler

    run_spike_load_test "$set_no"
    wait_until_scaled_down_to_one

    stop_ml_autoscaler
  done

  log "=========================================="
  log "END ML SPIKE EXPERIMENT"
  log "=========================================="
}

log "ML experiment started"
log "SETS=$SETS"
log "TARGETS=$TARGETS"
log "TARGET_URL=$TARGET_URL"
log "PROM_URL=$PROM_URL"
log "ML direct scaling=$([ "$ML_HPA_LIKE_POLICY" = "true" ] && echo false || echo true)"
log "ML cooldown up/down=${ML_SCALE_UP_COOLDOWN_SECONDS}/${ML_SCALE_DOWN_COOLDOWN_SECONDS}s"
log "ML min-change=$ML_MIN_CHANGE"
log "ML max-pods=$ML_MAX_PODS"
log "ML idle-guard=$ML_IDLE_GUARD rps<=${ML_IDLE_RPS_THRESHOLD} in_progress<=${ML_IDLE_IN_PROGRESS_THRESHOLD} samples=${ML_IDLE_CONSECUTIVE_SAMPLES}"
log "SLO thresholds: latency>${ML_LATENCY_SLO_THRESHOLD}s OR error_rate>${ML_ERROR_RATE_SLO_THRESHOLD}"
log "DELAY_FACTOR=$DELAY_FACTOR CPU_FACTOR=$CPU_FACTOR ERROR_FACTOR=$ERROR_FACTOR"

check_required_files
check_prometheus
init_timeline_file

run_step_experiments
sleep 60
run_spike_experiments

# Final cleanup.
delete_autoscalers
kubectl scale deployment "$APP_NAME" --replicas=1 -n "$NAMESPACE" || true

log "DONE"
log "Timeline file: $TIMELINE_FILE"
log "ML live CSV:   $ML_OUTPUT_CSV"
log "ML live log:   $ML_LOG_FILE"
