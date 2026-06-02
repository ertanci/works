import http from 'k6/http';
import { check } from 'k6';

const TARGET_URL = __ENV.URL || 'http://localhost:3001';

const MEAN_RPS = Number(__ENV.MEAN_RPS || 150);
const TOTAL_MINUTES = Number(__ENV.TOTAL_MINUTES || 20);
const STEP_SECONDS = Number(__ENV.STEP_SECONDS || 120);

const PRE_ALLOCATED_VUS = Number(__ENV.PRE_ALLOCATED_VUS || 500);
const MAX_VUS = Number(__ENV.MAX_VUS || 1000);

const DELAY_FACTOR = Number(__ENV.DELAY_FACTOR || 1.2);
const CPU_FACTOR = Number(__ENV.CPU_FACTOR || 1.2);
const ERROR_FACTOR = Number(__ENV.ERROR_FACTOR || 1);

const SEED_INITIAL = Number(__ENV.SEED || 42);

const STEP_COUNT = Math.floor((TOTAL_MINUTES * 60) / STEP_SECONDS);

// Endpoint distribution:
// /light = 50%
// /heavy = 35%
// /error = 15%
const endpoints = [
  '/light', '/light', '/light', '/light', '/light',
  '/light', '/light', '/light', '/light', '/light',

  '/heavy', '/heavy', '/heavy', '/heavy', '/heavy',
  '/heavy', '/heavy',

  '/error', '/error', '/error',
];

const profiles = {
  '/light': {
    delay: 0.03,
    cpu_load: 0.02,
    error_rate: 1,
  },
  '/heavy': {
    delay: 0.08,
    cpu_load: 0.08,
    error_rate: 4,
  },
  '/error': {
    delay: 0.05,
    cpu_load: 0.03,
    error_rate: 15,
  },
};

// Deterministic pseudo-random generator.
// Same SEED value generates the same Poisson RPS sequence.
// This makes experiments reproducible.
let seed = SEED_INITIAL >>> 0;

function random() {
  seed = (1664525 * seed + 1013904223) >>> 0;
  return seed / 4294967296;
}

function poissonRandom(lambda) {
  if (lambda <= 0) {
    return 0;
  }

  // Exact Poisson sampling using Knuth's algorithm.
  //
  // In this workload, only one sample is generated per stage.
  // Total stage count is 10, so this method is simple,
  // academically explainable, and efficient enough.
  //
  // RPS_i ~ Poisson(lambda)
  const L = Math.exp(-lambda);
  let k = 0;
  let p = 1;

  do {
    k += 1;
    p *= random();
  } while (p > L);

  return Math.max(1, k - 1);
}

function buildStages() {
  const stages = [];

  for (let i = 0; i < STEP_COUNT; i++) {
    const targetRps = poissonRandom(MEAN_RPS);

    stages.push({
      duration: `${STEP_SECONDS}s`,
      target: targetRps,
    });
  }

  return stages;
}

const stages = buildStages();

console.log('Poisson arrival-rate workload');
console.log(`SEED=${SEED_INITIAL}`);
console.log(`MEAN_RPS=${MEAN_RPS}`);
console.log(`TOTAL_MINUTES=${TOTAL_MINUTES}`);
console.log(`STEP_SECONDS=${STEP_SECONDS}`);
console.log(`STEP_COUNT=${STEP_COUNT}`);
console.log('Generated Poisson RPS stages:');
console.log(JSON.stringify(stages, null, 2));

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],

  scenarios: {
    poisson_arrival_rate: {
      executor: 'ramping-arrival-rate',
      timeUnit: '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages,
      gracefulStop: '30s',
    },
  }
};

export default function () {
  const endpoint = endpoints[__ITER % endpoints.length];
  const profile = profiles[endpoint];

  const delay = profile.delay * DELAY_FACTOR;
  const cpuLoad = profile.cpu_load * CPU_FACTOR;
  const errorRate = Math.round(profile.error_rate * ERROR_FACTOR);

  const url = `${TARGET_URL}${endpoint}?delay=${delay}&error_rate=${errorRate}&cpu_load=${cpuLoad}`;

  const res = http.get(url);

  check(res, {
    'response completed': (r) => r.status >= 200 && r.status < 600,
  });

  // No sleep is used here.
  // ramping-arrival-rate controls the request arrival rate directly.
}