import http from 'k6/http';
import { sleep, check } from 'k6';

const TARGET_URL = __ENV.URL || 'http://localhost:3001';

const TARGET_VUS = Number(__ENV.TARGET_VUS || 50);

const DELAY_FACTOR = Number(__ENV.DELAY_FACTOR || 1.3);
const CPU_FACTOR = Number(__ENV.CPU_FACTOR || 1.3);
const ERROR_FACTOR = Number(__ENV.ERROR_FACTOR || 1.3);

// 50% light, 35% heavy, 15% error
const endpoints = [
  '/light', '/light', '/light', '/light', '/light',
  '/light', '/light', '/light', '/light', '/light',

  '/heavy', '/heavy', '/heavy', '/heavy', '/heavy',
  '/heavy', '/heavy',

  '/error', '/error', '/error'
];

const profiles = {
  '/light': {
    delay: 0.03,
    cpu_load: 0.02,
    error_rate: 1
  },
  '/heavy': {
    delay: 0.08,
    cpu_load: 0.08,
    error_rate: 4
  },
  '/error': {
    delay: 0.05,
    cpu_load: 0.03,
    error_rate: 15
  }
};

function buildStages(target) {
  const stages = [];

  stages.push({ duration: '1m', target: 25 });

  if (target >= 50) {
    stages.push({ duration: '2m', target: 50 });
  }

  if (target >= 100) {
    stages.push({ duration: '2m', target: 100 });
  }

  if (target >= 150) {
    stages.push({ duration: '2m', target: 150 });
  }

  if (target >= 200) {
    stages.push({ duration: '2m', target: 200 });
  }

  if (target >= 300) {
    stages.push({ duration: '2m', target: 300 });
  }

  if (target >= 400) {
    stages.push({ duration: '2m', target: 400 });
  }

  stages.push({ duration: '3m', target: target });
  stages.push({ duration: '1m', target: 0 });

  return stages;
}

export const options = {
  scenarios: {
    step_load_test: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: buildStages(TARGET_VUS),
      gracefulRampDown: '30s',
      gracefulStop: '30s'
    }
  },
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<1500']
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
    'response completed': (r) => r.status >= 200 && r.status < 600
  });

  sleep(1);
}