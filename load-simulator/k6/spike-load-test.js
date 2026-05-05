import http from 'k6/http';
import { sleep, check } from 'k6';

const TARGET_URL = __ENV.URL || 'http://localhost:3001';

const DELAY_FACTOR = Number(__ENV.DELAY_FACTOR || 1.2);
const CPU_FACTOR = Number(__ENV.CPU_FACTOR || 1.2);
const ERROR_FACTOR = Number(__ENV.ERROR_FACTOR || 1);

const SPIKE_TARGET_VUS = Number(__ENV.SPIKE_TARGET_VUS || 400);
const BASELINE_VUS = Number(__ENV.BASELINE_VUS || 50);

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

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  
  scenarios: {
    spike_test: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        // Baseline: normal trafik
        { duration: '1m', target: BASELINE_VUS },
        { duration: '2m', target: BASELINE_VUS },

        // Spike: ani trafik artışı
        { duration: '15s', target: SPIKE_TARGET_VUS },

        // Peak hold: zirvede kalma
        { duration: '3m', target: SPIKE_TARGET_VUS },

        // Recovery: normal trafiğe dönüş
        { duration: '30s', target: BASELINE_VUS },

        // Cooldown
        { duration: '1m', target: BASELINE_VUS },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
      gracefulStop: '30s',
    }
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