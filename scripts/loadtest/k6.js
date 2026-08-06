// k6 script for a real load rig. Run:  k6 run scripts/loadtest/k6.js
//
// This exists alongside harness.py because a single Python process cannot
// generate enough load to find a properly sized server's limit, and its latency
// figures include its own scheduling noise. k6 generates load in Go, aggregates
// percentiles correctly, and can be run distributed.
//
// The thresholds below are the ones worth failing a build over. They are
// intentionally modest: a threshold nobody can meet gets deleted, and a deleted
// threshold protects nothing.
import http from 'k6/http';
import { check, group, sleep } from 'k6';

export const options = {
  scenarios: {
    // Steady browsing, which is what most traffic actually is.
    browse: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 50 },
        { duration: '2m', target: 50 },
        { duration: '30s', target: 0 },
      ],
      exec: 'browse',
    },
    // A burst, which is what a broadcast to every customer causes: everyone
    // opens the Mini App within about ninety seconds.
    burst: {
      executor: 'constant-arrival-rate',
      rate: 200,
      timeUnit: '1s',
      duration: '1m',
      preAllocatedVUs: 100,
      maxVUs: 400,
      startTime: '3m',
      exec: 'browse',
    },
  },
  thresholds: {
    'http_req_duration{scenario:browse}': ['p(95)<500', 'p(99)<1500'],
    // 429s are a correct response under the burst scenario, so only real
    // failures count against this threshold.
    'http_req_failed': ['rate<0.01'],
    'checks': ['rate>0.99'],
  },
};

const BASE = __ENV.BASE_URL || 'http://localhost:8000';

export function browse() {
  group('catalog', () => {
    const response = http.get(`${BASE}/api/v1/catalog/products`);
    check(response, {
      // 429 is accepted: being refused politely is correct behaviour, not a failure.
      'answered (2xx or 429)': (r) => (r.status >= 200 && r.status < 300) || r.status === 429,
      'security headers present': (r) =>
        r.headers['X-Content-Type-Options'] === 'nosniff' &&
        r.headers['Content-Security-Policy'] !== undefined,
      'rate limit headers present': (r) => r.headers['X-Ratelimit-Limit'] !== undefined,
      'correlation id returned': (r) => r.headers['X-Correlation-Id'] !== undefined,
    });
  });
  sleep(Math.random() * 2);
}

export function handleSummary(data) {
  return { 'loadtest-summary.json': JSON.stringify(data, null, 2) };
}
