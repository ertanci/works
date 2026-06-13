#!/bin/bash

set -e

# ============================================================
# Spike Experiment Runner
#
# Flow:
#   Set 1:
#     HPA  spike test
#     cleanup
#     KEDA spike test
#     cleanup
#
#   Set 2:
#     HPA  spike test
#     cleanup
#     KEDA spike test
#     cleanup
#
# Notes:
#   - No external parameter is required.
#   - Each autoscaler starts from a clean 1-replica state.
#   - After each spike test, the script waits for natural scale-down.
# ============================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$ROOT_DIR/../results/metrics"
TIMELINE_FILE="$DATA_DIR/experiment_timeline.csv"
mkdir -p "$DATA_DIR"

APP_NAME="autoscale-test-service"
NAMESPACE="default"

HPA_FILE="$ROOT_DIR/../autoscale-test-service/hpa.yaml"
KEDA_FILE="$ROOT_DIR/../autoscale-test-service/keda-slo.yaml"
LOAD_SCRIPT="$ROOT_DIR/../k6/spike-load-test.js"
RESULT_DIR="$ROOT_DIR/../results/k6/spike-load"

SERVICE_URL="http://localhost:3001/health"
TARGET_URL="http://localhost:3001"

SETS=1

BASELINE_VUS=50
SPIKE_TARGET_VUS=400

DELAY_FACTOR=1.2
CPU_FACTOR=1.2
ERROR_FACTOR=1

INITIAL_STABILIZATION_SECONDS=60
AUTOSCALER_STABILIZATION_SECONDS=30
POST_SCALE_DOWN_STABILIZATION_SECONDS=60

SCALE_DOWN_TIMEOUT_SECONDS=900
SCALE_DOWN_CHECK_INTERVAL_SECONDS=10

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

file_timestamp() {
  date +"%Y%m%d_%H%M%S"
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
    echo "ERROR: Spike load script not found: $LOAD_SCRIPT"
    exit 1
  fi

  mkdir -p "$RESULT_DIR"
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

run_spike_test() {
  autoscaler="$1"
  set_no="$2"
  
  RUN_ID="$(date +%Y%m%d_%H%M%S)_${autoscaler}_Spike_Set${set_no}_${BASELINE_VUS}_to_${SPIKE_TARGET_VUS}"
  RESULT_FILE="$RESULT_DIR/${RUN_ID}_summary.json"

  START_TS="$(date +%s)"

  log "=========================================="
  log "START SPIKE TEST | autoscaler=${autoscaler} | set=${set_no}/${SETS}"
  log "RESULT_FILE=$RESULT_FILE"
  log "=========================================="

  URL="$TARGET_URL" \
  DELAY_FACTOR="$DELAY_FACTOR" \
  CPU_FACTOR="$CPU_FACTOR" \
  ERROR_FACTOR="$ERROR_FACTOR" \
  BASELINE_VUS="$BASELINE_VUS" \
  SPIKE_TARGET_VUS="$SPIKE_TARGET_VUS" \
  k6 run --summary-export "$RESULT_FILE" "$LOAD_SCRIPT"

  END_TS="$(date +%s)"

  write_timeline_event \
    "$RUN_ID" \
    "spike" \
    "$autoscaler" \
    "$set_no" \
    "$SPIKE_TARGET_VUS" \
    "$BASELINE_VUS" \
    "$SPIKE_TARGET_VUS" \
    "$START_TS" \
    "$END_TS"

  log "END SPIKE TEST | autoscaler=${autoscaler} | set=${set_no}/${SETS}"
}

run_hpa_spike() {
  set_no="$1"

  log "##########################################"
  log "HPA SPIKE SET ${set_no}/${SETS}"
  log "##########################################"

  prepare_clean_start
  apply_hpa
  run_spike_test "HPA" "$set_no"
  wait_until_scaled_down_to_one

  log "Cleaning after HPA spike set ${set_no}"
  delete_autoscalers
}

run_keda_spike() {
  set_no="$1"

  log "##########################################"
  log "KEDA SPIKE SET ${set_no}/${SETS}"
  log "##########################################"

  prepare_clean_start
  apply_keda
  run_spike_test "KEDA" "$set_no"
  wait_until_scaled_down_to_one

  log "Cleaning after KEDA spike set ${set_no}"
  delete_autoscalers
}

log "Spike experiment started"
log "SETS=$SETS"
log "BASELINE_VUS=$BASELINE_VUS"
log "SPIKE_TARGET_VUS=$SPIKE_TARGET_VUS"
log "TARGET_URL=$TARGET_URL"
log "DELAY_FACTOR=$DELAY_FACTOR CPU_FACTOR=$CPU_FACTOR ERROR_FACTOR=$ERROR_FACTOR"

check_required_files
init_timeline_file

for set_no in $(seq 1 "$SETS"); do
  log "=========================================="
  log "START SPIKE EXPERIMENT SET ${set_no}/${SETS}"
  log "=========================================="

  run_hpa_spike "$set_no"
  run_keda_spike "$set_no"

  log "=========================================="
  log "END SPIKE EXPERIMENT SET ${set_no}/${SETS}"
  log "=========================================="
done

log "Final cleanup"
delete_autoscalers

log "DONE"