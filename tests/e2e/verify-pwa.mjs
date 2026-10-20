import { chromium } from '../../src/frontend/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
const browser = await chromium.launch();
try {
  const context = await browser.newContext(),
    page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(30000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const baseURL = process.env.PWA_BASE_URL || process.env.DEPLOY_BASE_URL || 'http://127.0.0.1:4173';
  await page.goto(baseURL);
  // Polling has a finite timeout, including when registration fails or the origin
  // does not support service workers; navigator.serviceWorker.ready can hang.
  await page.waitForFunction(
    () => 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null,
    undefined,
    { timeout: 20000 },
  );
  const account = `pwa_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  const registration = await context.request.post(`${baseURL.replace(/\/$/, '')}/api/auth/register`, {
    data: { name: account, password: 'pwa-verification-test-only' },
  });
  assert.equal(registration.status(), 201, await registration.text());
  // Browser fetches pass through the controlling worker. Checking only a fresh
  // unauthenticated shell would never exercise caching of private responses.
  const authenticated = await page.evaluate(async () => {
    const results = [];
    for (const path of ['/api/auth/me', '/api/progress', '/api/exercises', '/api/repertoire']) {
      const response = await fetch(path, { credentials: 'same-origin' });
      results.push({ path, status: response.status });
      await response.text();
    }
    return results;
  });
  assert(authenticated.every((result) => result.status === 200), JSON.stringify(authenticated));
  const cached = await page.evaluate(async () => {
    const paths = [];
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      paths.push(...(await cache.keys()).map((request) => new URL(request.url).pathname));
    }
    return paths;
  });
  assert(
    cached.some((path) => path.endsWith('.js')),
    'JavaScript must be cached on the first visit',
  );
  assert(
    cached.some((path) => path.endsWith('.css')),
    'Styles must be cached on the first visit',
  );
  assert(!cached.some((path) => path.startsWith('/api')), 'Private API data must never enter the asset cache');
  await context.setOffline(true);
  await page.reload();
  try {
    await page.getByRole('heading', { name: 'Create account', exact: true }).waitFor({ timeout: 10000 });
  } catch (error) {
    console.log('OFFLINE DOM', await page.locator('body').innerText());
    console.log('CACHE', cached);
    throw error;
  }
  assert(await page.getByRole('button', { name: 'Create account', exact: true }).isVisible());
  assert.deepEqual(errors, []);
  console.log(
    'Production PWA passed: bounded first-visit service-worker control; JS/CSS shell precached; authenticated API responses excluded from every cache; offline reload renders.',
  );
} finally {
  await browser.close();
}
