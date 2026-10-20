import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';

test('material tracks history and exploration; LLM connection saves privately', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const registered = await page.request.post('/api/auth/register', {
    data: {
      name: `score_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      password: 'score-settings-test-only',
    },
  });
  expect(registered.status()).toBe(201);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await expect(page.locator('.position-score')).toContainText('Equal material');
  await page.getByRole('button', { name: 'Import FEN / PGN', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'FEN / PGN', exact: true })
    .fill('[Event "Material score"]\n\n1. e4 d5 2. exd5 *');
  await page.getByRole('button', { name: 'Load position', exact: true }).click();
  const score = page.locator('.position-score');
  await expect(score).toContainText('White leads in material +1');
  await expect(score.locator('.material-score')).toContainText('White 39');
  await expect(score.locator('.material-score')).toContainText('Black 38');
  await page.getByRole('button', { name: 'Starting position', exact: true }).click();
  await expect(score).toContainText('Equal material');
  await page.getByRole('button', { name: 'Latest position', exact: true }).click();
  await page.getByRole('button', { name: 'Flip board', exact: true }).click();
  await expect(score).toContainText('White leads in material +1');
  await mkdir('/tmp/chessmate-score-settings', { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `/tmp/chessmate-score-settings/${info.project.name}-score.png` });
  if (info.project.name === 'desktop')
    await score.screenshot({ path: '/tmp/chessmate-score-settings/score-detail.png' });
  await page.getByRole('button', { name: 'Explore position', exact: true }).click();
  for (const square of ['d8', 'd5']) {
    const target = page.locator(`[data-square="${square}"]`);
    if (info.project.name === 'desktop') await target.click();
    else await target.tap();
  }
  await expect(score).toContainText('Equal material');
  await page.getByRole('button', { name: 'Return to game', exact: true }).click();
  await expect(score).toContainText('White leads in material +1');

  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('LLM endpoint', { exact: true }).fill('http://host.docker.internal:8000/v1');
  await page.getByLabel('Model', { exact: true }).fill('fixture-local-model');
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(page.getByText('Connection saved', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/settings/llm')).json()).has_api_key).toBe(false);
  await page.getByLabel('API key (optional)', { exact: true }).fill('fixture-only-browser-key');
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(page.getByText('Connection saved', { exact: true })).toBeVisible();
  const saved = await page.request.get('/api/settings/llm');
  expect((await saved.json()).has_api_key).toBe(true);
  expect(await saved.text()).not.toContain('fixture-only-browser-key');
  await expect(page.getByLabel('API key (optional)', { exact: true })).toHaveValue('');
  await page.reload();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByLabel('LLM endpoint', { exact: true })).toHaveValue('http://host.docker.internal:8000/v1');
  await expect(page.getByLabel('Model', { exact: true })).toHaveValue('fixture-local-model');
  await expect(page.getByLabel('API key (optional)', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('API key (optional)', { exact: true })).toHaveAttribute(
    'placeholder',
    'Key saved · leave blank to keep',
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `/tmp/chessmate-score-settings/${info.project.name}-settings.png` });
  if (info.project.name === 'desktop')
    await page
      .locator('section')
      .filter({ has: page.getByRole('heading', { name: 'LLM connection', exact: true }) })
      .screenshot({ path: '/tmp/chessmate-score-settings/settings-detail.png' });
  await page.getByRole('switch', { name: 'Remove saved API key', exact: true }).check();
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(page.getByText('Connection saved', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/settings/llm')).json()).has_api_key).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
