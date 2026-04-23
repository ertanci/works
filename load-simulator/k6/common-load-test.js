import http from 'k6/http';
import { sleep, check } from 'k6';

const TARGET_URL = __ENV.URL || 'http://localhost:3001';
const DELAY = __ENV.DELAY || '0.05';
const ERROR_RATE = __ENV.ERROR_RATE || '2';
const CPU_LOAD = __ENV.CPU_LOAD || '0.05';

// Deterministic endpoint distribution:
// 50% light, 35% heavy, 15% error
const endpoints = [
  '/light', '/light', '/light', '/light', '/light',
  '/light', '/light', '/light', '/light', '/light',

  '/heavy', '/heavy', '/heavy', '/heavy', '/heavy',
  '/heavy', '/heavy',

  '/error', '/error', '/error'
];

export const options = {
  scenarios: {
    common_autoscaling_test: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 25 },
        { duration: '2m', target: 50 },
        { duration: '2m', target: 100 },
        { duration: '2m', target: 150 },
        { duration: '2m', target: 200 },
        { duration: '2m', target: 0 }
      ]
    }
  },
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<1000']
  }
};

export default function () {
  const endpoint = endpoints[__ITER % endpoints.length];

  const url = `${TARGET_URL}${endpoint}?delay=${DELAY}&error_rate=${ERROR_RATE}&cpu_load=${CPU_LOAD}`;

  const res = http.get(url);

  check(res, {
    'response completed': (r) => r.status >= 200 && r.status < 600
  });

  sleep(1);
}