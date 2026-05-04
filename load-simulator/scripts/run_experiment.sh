#!/bin/bash

set -e

# ============================================================
# Autoscaling Experiment Runner
# HPA and KEDA comparison with repeated step-load experiments
#
# Flow:
#   1. Reset system
#   2. Apply HPA
#   3. Run 5 sets: 50 -> calm -> 100 -> calm -> 200 -> calm -> 400 -> calm
#   4. Reset system
#   5. Apply KEDA
#   6. Run same 5 sets
# ============================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_NAME="autoscale-test-service"
NAMESPACE="default"

HPA_FILE="$ROOT_DIR/../autoscale-test-service/hpa.yaml"
KEDA_FILE="$ROOT_DIR/../autoscale-test-service/keda-slo.yaml"

LOAD_SCRIPT="$ROOT_DIR/../k6/step-load-test.js"

SERVICE_URL="${SERVICE_URL:-http://localhost:3001/health}"
TARGET_URL="${URL:-http://localhost:3001}"

SETS="${SETS:-1}"
TARGETS="${TARGETS:-50 100 200 400}"

INITIAL_STABILIZATION_SECONDS="${INITIAL_STABILIZATION_SECONDS:-60}"
AUTOSCALER_STABILIZATION_SECONDS="${AUTOSCALER_STABILIZATION_SECONDS:-30}"
POST_SCALE_DOWN_STABILIZATION_SECONDS="${POST_SCALE_DOWN_STABILIZATION_SECONDS:-60}"

SCALE_DOWN_TIMEOUT_SECONDS="${SCALE_DOWN_TIMEOUT_SECONDS:-600}"
SCALE_DOWN_CHECK_INTERVAL_SECONDS="${SCALE_DOWN_CHECK_INTERVAL_SECONDS:-10}"

DELAY_FACTOR="${DELAY_FACTOR:-1.3}"
CPU_FACTOR="${CPU_FACTOR:-1.3}"
ERROR_FACTOR="${ERROR_FACTOR:-1.3}"
RESULT_FILE="$ROOT_DIR/../results/${autoscaler}_Set${set_no}_${target_vus}VUs.json"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log() {
  echo ""
  echo "[$(timestamp)] $1"
}

delete_autoscalers() {
  log "Deleting HPA and KEDA ScaledObjects"
  kubectl delete hpa --all -n "$NAMESPACE" || true
  kubectl delete scaledobject --all -n "$NAMESPACE" || true
}

check_app_health() {
  log "Checking app health: $SERVICE_URL"

  for i in {1..30}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL" || true)

    if [ "$STATUS" == "200" ]; then
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
    replicas=$(get_available_replicas)

    echo "Current available replicas: $replicas | elapsed=${elapsed}s"

    if [ "$replicas" == "1" ]; then
      log "Deployment returned to 1 available replica"
      log "Sleeping ${POST_SCALE_DOWN_STABILIZATION_SECONDS}s after scale-down"
      sleep "$POST_SCALE_DOWN_STABILIZATION_SECONDS"
      return 0
    fi

    sleep "$SCALE_DOWN_CHECK_INTERVAL_SECONDS"
    elapsed=$((elapsed + SCALE_DOWN_CHECK_INTERVAL_SECONDS))
  done

  echo "WARNING: Scale-down timeout reached. Continuing with next test."
  echo "Current available replicas: $(get_available_replicas)"
}

apply_hpa() {
  log "Applying HPA: $HPA_FILE"
  kubectl apply -f "$HPA_FILE" -n "$NAMESPACE"

  log "Sleeping ${AUTOSCALER_STABILIZATION_SECONDS}s after applying HPA"
  sleep "$AUTOSCALER_STABILIZATION_SECONDS"
}

apply_keda() {
  log "Applying KEDA: $KEDA_FILE"
  kubectl apply -f "$KEDA_FILE" -n "$NAMESPACE"

  log "Sleeping ${AUTOSCALER_STABILIZATION_SECONDS}s after applying KEDA"
  sleep "$AUTOSCALER_STABILIZATION_SECONDS"
}

run_load_test() {
  autoscaler="$1"
  set_no="$2"
  target_vus="$3"

  log "START LOAD | autoscaler=${autoscaler} | set=${set_no}/${SETS} | target_vus=${target_vus}"

  URL="$TARGET_URL" \
  TARGET_VUS="$target_vus" \
  DELAY_FACTOR="$DELAY_FACTOR" \
  CPU_FACTOR="$CPU_FACTOR" \
  ERROR_FACTOR="$ERROR_FACTOR" \
  k6 run --out json="$RESULT_FILE" "$LOAD_SCRIPT" 

  log "END LOAD | autoscaler=${autoscaler} | set=${set_no}/${SETS} | target_vus=${target_vus}"
}

run_experiment_for_autoscaler() {
  autoscaler="$1"

  log "=========================================="
  log "START AUTOSCALER EXPERIMENT: $autoscaler"
  log "=========================================="

  for set_no in $(seq 1 "$SETS"); do
    log "========== ${autoscaler} | SET ${set_no}/${SETS} =========="

    for target_vus in $TARGETS; do
      run_load_test "$autoscaler" "$set_no" "$target_vus"
      wait_until_scaled_down_to_one
    done
  done

  log "=========================================="
  log "END AUTOSCALER EXPERIMENT: $autoscaler"
  log "=========================================="
}

log "Experiment started"
log "SETS=$SETS"
log "TARGETS=$TARGETS"
log "TARGET_URL=$TARGET_URL"
log "DELAY_FACTOR=$DELAY_FACTOR CPU_FACTOR=$CPU_FACTOR ERROR_FACTOR=$ERROR_FACTOR"

if [ ! -f "$LOAD_SCRIPT" ]; then
  echo "ERROR: Load script not found: $LOAD_SCRIPT"
  exit 1
fi

if [ ! -f "$HPA_FILE" ]; then
  echo "ERROR: HPA file not found: $HPA_FILE"
  exit 1
fi

if [ ! -f "$KEDA_FILE" ]; then
  echo "ERROR: KEDA file not found: $KEDA_FILE"
  exit 1
fi

delete_autoscalers
reset_app_to_one_replica
apply_hpa
run_experiment_for_autoscaler "HPA"

delete_autoscalers
reset_app_to_one_replica
apply_keda
run_experiment_for_autoscaler "KEDA"

# Final cleanup is optional.
# delete_autoscalers

log "DONE"