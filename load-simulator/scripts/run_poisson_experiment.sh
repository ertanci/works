#!/bin/bash

set -e

# ============================================================
# Poisson Arrival-Rate Experiment Runner
#
# Purpose:
#   - Collect new Poisson arrival-rate workload data.
#   - Do not modify existing step/spike experiment scripts.
#   - Use the same HPA and KEDA experiment logic.
#
# Workload:
#   RPS_i ~ Poisson(lambda)
#   lambda = 150
#   total duration = 18 minutes
#   step duration = 180 seconds
#   stage count = 6
# ============================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="$ROOT_DIR/../results/metrics"
TIMELINE_FILE="$DATA_DIR/experiment_timeline.csv"

APP_NAME="autoscale-test-service"
NAMESPACE="default"

HPA_FILE="$ROOT_DIR/../autoscale-test-service/hpa.yaml"
KEDA_FILE="$ROOT_DIR/../autoscale-test-service/keda-slo.yaml"
LOAD_SCRIPT="$ROOT_DIR/../k6/poisson-arrival-rate.js"

RESULT_DIR="$ROOT_DIR/../results/k6/poisson-arrival-rate"

SERVICE_URL="http://localhost:3001/health"
TARGET_URL="http://localhost:3001"

SETS="${SETS:-5}"

MEAN_RPS="${MEAN_RPS:-110}"
TOTAL_MINUTES="${TOTAL_MINUTES:-18}"
STEP_SECONDS="${STEP_SECONDS:-180}"

PRE_ALLOCATED_VUS="${PRE_ALLOCATED_VUS:-300}"
MAX_VUS="${MAX_VUS:-700}"

DELAY_FACTOR="${DELAY_FACTOR:-1.2}"
CPU_FACTOR="${CPU_FACTOR:-1.2}"
ERROR_FACTOR="${ERROR_FACTOR:-1}"

INITIAL_STABILIZATION_SECONDS=60
AUTOSCALER_STABILIZATION_SECONDS=30
POST_SCALE_DOWN_STABILIZATION_SECONDS=60

SCALE_DOWN_TIMEOUT_SECONDS=900
SCALE_DOWN_CHECK_INTERVAL_SECONDS=10

mkdir -p "$DATA_DIR"
mkdir -p "$RESULT_DIR"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log() {
  echo ""
  echo "[$(timestamp)] $1"
}

check_required_files() {
  if [ ! -f "$HPA_FILE" ]; then
    echo "ERROR: HPA file not found: $HPA_FILE"
    exit 1
  fi

  if [ ! -f "$KEDA_FILE" ]; then
    echo "ERROR: KEDA file not found: $KEDA_FILE"
    exit 1
  fi

  if [ ! -f "$LOAD_SCRIPT" ]; then
    echo "ERROR: Poisson load script not found: $LOAD_SCRIPT"
    exit 1
  fi
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

delete_autoscalers() {
  log "Deleting autoscalers"

  kubectl delete scaledobject --all -n "$NAMESPACE" || true
  kubectl delete hpa --all -n "$NAMESPACE" || true
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

prepare_clean_start() {
  log "Preparing clean start with 1 replica"

  delete_autoscalers

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

  echo "WARNING: Scale-down timeout reached. Continuing with cleanup."
  echo "Current available replicas: $(get_available_replicas)"
}

apply_hpa() {
  log "Applying HPA: $HPA_FILE"

  kubectl apply -f "$HPA_FILE" -n "$NAMESPACE"

  log "Sleeping ${AUTOSCALER_STABILIZATION_SECONDS}s after applying HPA"
  sleep "$AUTOSCALER_STABILIZATION_SECONDS"

  kubectl get hpa -n "$NAMESPACE"
}

apply_keda() {
  log "Applying KEDA: $KEDA_FILE"

  kubectl apply -f "$KEDA_FILE" -n "$NAMESPACE"

  log "Sleeping ${AUTOSCALER_STABILIZATION_SECONDS}s after applying KEDA"
  sleep "$AUTOSCALER_STABILIZATION_SECONDS"

  kubectl get scaledobject -n "$NAMESPACE" || true
  kubectl get hpa -n "$NAMESPACE" || true
}

run_poisson_test() {
  autoscaler="$1"
  set_no="$2"

  seed="$((1000 + set_no))"

  RUN_ID="$(date +%Y%m%d_%H%M%S)_${autoscaler}_Poisson_Set${set_no}_Mean${MEAN_RPS}RPS"
  RESULT_FILE="$RESULT_DIR/${RUN_ID}_summary.json"

  START_TS="$(date +%s)"

  log "=========================================="
  log "START POISSON TEST | autoscaler=${autoscaler} | set=${set_no}/${SETS}"
  log "MEAN_RPS=${MEAN_RPS}"
  log "TOTAL_MINUTES=${TOTAL_MINUTES}"
  log "STEP_SECONDS=${STEP_SECONDS}"
  log "SEED=${seed}"
  log "RESULT_FILE=$RESULT_FILE"
  log "=========================================="

  URL="$TARGET_URL" \
  MEAN_RPS="$MEAN_RPS" \
  TOTAL_MINUTES="$TOTAL_MINUTES" \
  STEP_SECONDS="$STEP_SECONDS" \
  PRE_ALLOCATED_VUS="$PRE_ALLOCATED_VUS" \
  MAX_VUS="$MAX_VUS" \
  DELAY_FACTOR="$DELAY_FACTOR" \
  CPU_FACTOR="$CPU_FACTOR" \
  ERROR_FACTOR="$ERROR_FACTOR" \
  SEED="$seed" \
  k6 run --summary-export "$RESULT_FILE" "$LOAD_SCRIPT"

  END_TS="$(date +%s)"

  write_timeline_event \
    "$RUN_ID" \
    "poisson-arrival-rate" \
    "$autoscaler" \
    "$set_no" \
    "$MEAN_RPS" \
    "0" \
    "0" \
    "$START_TS" \
    "$END_TS"

  log "END POISSON TEST | autoscaler=${autoscaler} | set=${set_no}/${SETS}"
}

run_hpa_poisson() {
  set_no="$1"

  log "##########################################"
  log "HPA POISSON SET ${set_no}/${SETS}"
  log "##########################################"

  prepare_clean_start
  apply_hpa
  run_poisson_test "HPA" "$set_no"
  wait_until_scaled_down_to_one

  log "Cleaning after HPA poisson set ${set_no}"
  delete_autoscalers
}

run_keda_poisson() {
  set_no="$1"

  log "##########################################"
  log "KEDA POISSON SET ${set_no}/${SETS}"
  log "##########################################"

  prepare_clean_start
  apply_keda
  run_poisson_test "KEDA" "$set_no"
  wait_until_scaled_down_to_one

  log "Cleaning after KEDA poisson set ${set_no}"
  delete_autoscalers
}

log "Poisson experiment started"
log "SETS=$SETS"
log "MEAN_RPS=$MEAN_RPS"
log "TOTAL_MINUTES=$TOTAL_MINUTES"
log "STEP_SECONDS=$STEP_SECONDS"
log "TARGET_URL=$TARGET_URL"
log "DELAY_FACTOR=$DELAY_FACTOR CPU_FACTOR=$CPU_FACTOR ERROR_FACTOR=$ERROR_FACTOR"

check_required_files
init_timeline_file

for set_no in $(seq 1 "$SETS"); do
  log "=========================================="
  log "START POISSON EXPERIMENT SET ${set_no}/${SETS}"
  log "=========================================="

  run_hpa_poisson "$set_no"
  run_keda_poisson "$set_no"

  log "=========================================="
  log "END POISSON EXPERIMENT SET ${set_no}/${SETS}"
  log "=========================================="
done

log "Final cleanup"
delete_autoscalers

log "DONE"