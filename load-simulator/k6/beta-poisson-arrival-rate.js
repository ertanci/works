import http from 'k6/http';
import { check } from 'k6';

const TARGET_URL = __ENV.URL || 'http://localhost:3001';

const MIN_RPS = Number(__ENV.MIN_RPS || 30);
const MAX_RPS = Number(__ENV.MAX_RPS || 300);
const TOTAL_MINUTES = Number(__ENV.TOTAL_MINUTES || 20);
const STEP_SECONDS = Number(__ENV.STEP_SECONDS || 120);

const BETA_ALPHA = Number(__ENV.BETA_ALPHA || 2);
const BETA_BETA = Number(__ENV.BETA_BETA || 5);

const PRE_ALLOCATED_VUS = Number(__ENV.PRE_ALLOCATED_VUS || 500);
const MAX_VUS = Number(__ENV.MAX_VUS || 1000);

const DELAY_FACTOR = Number(__ENV.DELAY_FACTOR || 1.2);
const CPU_FACTOR = Number(__ENV.CPU_FACTOR || 1.2);
const ERROR_FACTOR = Number(__ENV.ERROR_FACTOR || 1);

const SEED_INITIAL = Number(__ENV.SEED || 42);

const STEP_COUNT = Math.floor((TOTAL_MINUTES * 60) / STEP_SECONDS);

// 50% light, 35% heavy, 15% error
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

// ------------------------------------------------------------
// Deterministic pseudo-random generator
// Same SEED => same stage list for HPA/KEDA/ML.
// ------------------------------------------------------------
let seed = SEED_INITIAL >>> 0;

function random() {
  seed = (1664525 * seed + 1013904223) >>> 0;
  return seed / 4294967296;
}

function normalRandom() {
  const u1 = Math.max(random(), 1e-12);
  const u2 = Math.max(random(), 1e-12);

  return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
}

function gammaRandom(shape) {
  // Marsaglia and Tsang method.
  // Needed to sample Beta(alpha, beta).
  if (shape <= 0) {
    throw new Error(`Gamma shape must be positive. Got: ${shape}`);
  }

  if (shape < 1) {
    const u = Math.max(random(), 1e-12);
    return gammaRandom(shape + 1) * Math.pow(u, 1 / shape);
  }

  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);

  while (true) {
    const x = normalRandom();
    let v = 1 + c * x;

    if (v <= 0) {
      continue;
    }

    v = v * v * v;
    const u = random();

    if (u < 1 - 0.0331 * x * x * x * x) {
      return d * v;
    }

    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) {
      return d * v;
    }
  }
}

function betaRandom(alpha, beta) {
  const x = gammaRandom(alpha);
  const y = gammaRandom(beta);

  return x / (x + y);
}

function poissonRandom(lambda) {
  // For this experiment lambda is large:
  // lambda = RPS * STEP_SECONDS, e.g. 30*120=3600.
  // Exact Poisson sampling would be expensive.
  // Normal approximation is acceptable here:
  // Poisson(lambda) ~= Normal(lambda, sqrt(lambda)).
  const value = Math.round(lambda + Math.sqrt(lambda) * normalRandom());
  return Math.max(0, value);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function buildStages() {
  const stages = [];

  for (let i = 0; i < STEP_COUNT; i++) {
    // 1) Traffic intensity in [0,1]
    const x = betaRandom(BETA_ALPHA, BETA_BETA);

    // 2) Convert intensity to base RPS
    const baseRps = MIN_RPS + x * (MAX_RPS - MIN_RPS);

    // 3) Poisson request count for this time window
    const lambda = baseRps * STEP_SECONDS;
    const requestCount = poissonRandom(lambda);

    // 4) Convert request count back to RPS
    const sampledRps = requestCount / STEP_SECONDS;
    const targetRps = Math.round(clamp(sampledRps, MIN_RPS, MAX_RPS));

    stages.push({
      duration: `${STEP_SECONDS}s`,
      target: targetRps,
    });
  }

  return stages;
}

const stages = buildStages();

console.log('Beta + Poisson arrival-rate workload');
console.log(`SEED=${SEED_INITIAL}`);
console.log(`MIN_RPS=${MIN_RPS}`);
console.log(`MAX_RPS=${MAX_RPS}`);
console.log(`TOTAL_MINUTES=${TOTAL_MINUTES}`);
console.log(`STEP_SECONDS=${STEP_SECONDS}`);
console.log(`BETA_ALPHA=${BETA_ALPHA}`);
console.log(`BETA_BETA=${BETA_BETA}`);
console.log('Generated stages:');
console.log(JSON.stringify(stages, null, 2));

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],

  scenarios: {
    beta_poisson_arrival_rate: {
      executor: 'ramping-arrival-rate',
      timeUnit: '1s',
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
      stages,
      gracefulStop: '30s',
    },
  },

  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<500'],
  },
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

  // No sleep here.
  // ramping-arrival-rate controls request start rate.
}