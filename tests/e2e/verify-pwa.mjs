import { chromium } from '../../src/frontend/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
const browser = await chromium.launch();
let context, profileId;
const baseURL = process.env.PWA_BASE_URL || process.env.DEPLOY_BASE_URL || 'http://127.0.0.1:4173';
try {
  context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(30000);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(baseURL);
  // Polling has a finite timeout, including when registration fails or the origin
  // does not support service workers; navigator.serviceWorker.ready can hang.
  await page.waitForFunction(
    () => 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null,
    undefined,
    { timeout: 20000 },
  );
  const profile = `pwa_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  const creation = await context.request.post(`${baseURL.replace(/\/$/, '')}/api/profiles`, {
    data: { name: profile },
  });
  assert.equal(creation.status(), 201, await creation.text());
  profileId = (await creation.json()).id;
  await page.evaluate((id) => localStorage.setItem('chessmate.profile', id), profileId);
  await page.reload();
  await page.getByRole('heading', { name: 'Play', exact: true }).waitFor();
  // Browser fetches pass through the controlling worker. Checking only a fresh
  // unselected shell would never exercise caching of profile responses.
  const profiled = await page.evaluate(async () => {
    const results = [];
    for (const path of ['/api/profiles', '/api/progress', '/api/exercises', '/api/repertoire']) {
      const response = await fetch(path, {
        headers: { 'X-Profile-ID': localStorage.getItem('chessmate.profile') },
        credentials: 'same-origin',
      });
      results.push({ path, status: response.status });
      await response.text();
    }
    return results;
  });
  assert(
    profiled.every((result) => result.status === 200),
    JSON.stringify(profiled),
  );
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
    await page.getByRole('button', { name: 'Try again', exact: true }).waitFor({ timeout: 10000 });
    assert(await page.locator('.error-notice').isVisible());
  } catch (error) {
    console.log('OFFLINE DOM', await page.locator('body').innerText());
    console.log('CACHE', cached);
    throw error;
  }
  assert(await page.getByRole('button', { name: 'Try again', exact: true }).isVisible());
  assert.equal(
    await page.evaluate(() => localStorage.getItem('chessmate.profile')),
    profileId,
    'Offline load must preserve the selected profile',
  );
  await context.setOffline(false);
  await page.reload();
  await page.getByRole('heading', { name: 'Play', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(
    'Production PWA passed: bounded first-visit service-worker control; JS/CSS shell precached; profile API responses excluded from every cache; offline reload renders.',
  );
} finally {
  if (profileId) await context.request.delete(`${baseURL.replace(/\/$/, '')}/api/profiles/${profileId}`);
  await browser.close();
}
