import { writeFileSync } from 'node:fs';
// Build the proxy target at deploy time. Do NOT expose a database key here.
const origin = (process.env.BACKEND_ORIGIN || '').replace(/\/+$/, '');
if (origin && !/^https:\/\/[a-z0-9.-]+(?::\d+)?$/i.test(origin)) {
  throw new Error('BACKEND_ORIGIN must be an HTTPS origin without a path, e.g. https://api.example.com');
}
if (!origin) {
  console.warn('BACKEND_ORIGIN is empty: frontend preview will load, but hosted logins/data will NOT work.');
}
const lines = [
  ...(origin ? [`/api/*  ${origin}/api/:splat  200`] : []),
  '/*  /index.html  200', ''
];
writeFileSync('dist/_redirects', lines.join('\n'));
