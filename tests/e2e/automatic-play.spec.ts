import { mkdir } from 'node:fs/promises';
import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import type { Page, Route } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

async function createProfile(page: Page) {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/');
  await page
    .getByLabel('New profile', { exact: true })
    .fill(`auto_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`);
  const creation = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/profiles',
  );
  await page.getByRole('button', { name: 'Create profile', exact: true }).click();
  const created = await creation;
  expect(created.status(), await created.text()).toBe(201);
  const headers = { 'X-Profile-ID': (await created.json()).id as string };
  await expect(page.getByRole('button', { name: 'New game', exact: true })).toBeVisible();
  await expect(
    page.getByRole('heading', {
      name: 'Play',
      exact: true,
    }),
  ).toBeVisible();
  const settings = await page.request.get('/api/settings', { headers });
  expect(settings.status()).toBe(200);
  const preferences = await settings.json();
  expect(preferences.auto_computer, 'New players should receive automatic computer replies by default').toBe(true);
  return headers;
}

test.afterEach(async ({ page }) => {
  const profileId = await page.evaluate(() => localStorage.getItem('chessmate.profile'));
  if (profileId) await page.request.delete(`/api/profiles/${profileId}`);
});

async function start(page: Page, color: 'white' | 'black') {
  await page.getByRole('button', { name: 'New game', exact: true }).click();
  await page.getByLabel('Your color', { exact: true }).selectOption(color);
  const created = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/games',
  );
  await page.getByRole('button', { name: 'Start game', exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  return response.json();
}

async function move(page: Page, from: string, to: string) {
  const touch = await page.evaluate(() => navigator.maxTouchPoints > 0);
  for (const square of [from, to]) {
    const cell = page.locator(`[data-square="${square}"]`);
    if (touch) await cell.tap();
    else await cell.click();
  }
}

async function gameState(page: Page, id: string) {
  const profileId = await page.evaluate(() => localStorage.getItem('chessmate.profile'));
  const response = await page.request.get(`/api/games/${id}`, {
    headers: { 'X-Profile-ID': profileId! },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

function trackComputerCalls(page: Page) {
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && /^\/api\/games\/[^/]+\/computer$/.test(new URL(request.url()).pathname))
      calls.push(new URL(request.url()).pathname);
  });
  return (id: string) => calls.filter((path) => path === `/api/games/${id}/computer`).length;
}

// The 1.2–2.2 second observation windows exceed the UI's 900ms response delay.
// They assert the absence of unintended work rather than waiting for an element.
test('automatic white replies once, respects Explore/history/analysis, and retries errors only on request', async ({
  page,
}) => {
  const count = trackComputerCalls(page);
  await createProfile(page);
  const game = await start(page, 'white');
  expect(count(game.id)).toBe(0);
  await move(page, 'e2', 'e4');
  await expect.poll(async () => (await gameState(page, game.id)).moves.length).toBe(2);
  await expect(page.getByText('Your turn', { exact: true })).toBeVisible();
  expect(count(game.id)).toBe(1);
  const live = await gameState(page, game.id);
  expect(live.moves[0].uci).toBe('e2e4');
  expect(live.moves[1].source).toBe('computer');

  await page.getByRole('button', { name: 'Explore position', exact: true }).click();
  await move(page, 'g1', 'f3');
  await expect(page.getByText('Exploring a variation', { exact: true })).toBeVisible();
  await page.waitForTimeout(1200);
  expect(count(game.id)).toBe(1);
  expect((await gameState(page, game.id)).fen).toBe(live.fen);
  await page.getByRole('button', { name: 'Return to game', exact: true }).click();
  await page.getByRole('button', { name: 'Previous move', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Latest position', exact: true })).toBeEnabled();
  await page.waitForTimeout(1200);
  expect(count(game.id)).toBe(1);
  expect((await gameState(page, game.id)).moves).toHaveLength(2);
  await page.getByRole('button', { name: 'Latest position', exact: true }).click();

  let failures = 0;
  const failedEngine = async (route: Route) => {
    failures++;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Temporary test engine failure' }),
    });
  };
  await page.route(`**/api/games/${game.id}/computer`, failedEngine);
  await move(page, 'g1', 'f3');
  await expect.poll(() => failures).toBe(1);
  await expect(page.getByText('Temporary test engine failure', { exact: true })).toBeVisible();
  await page.waitForTimeout(2200);
  expect(failures, 'An engine outage must not create an automatic retry loop').toBe(1);
  expect(count(game.id)).toBe(2);
  expect((await gameState(page, game.id)).moves).toHaveLength(3);
  await page.unroute(`**/api/games/${game.id}/computer`, failedEngine);
  await page.getByRole('button', { name: 'Let computer move', exact: true }).click();
  await expect.poll(async () => (await gameState(page, game.id)).moves.length).toBe(4);
  await expect(page.getByText('Your turn', { exact: true })).toBeVisible();
  expect(count(game.id)).toBe(3);

  await page.getByRole('button', { name: 'Import FEN / PGN', exact: true }).click();
  await page.getByRole('textbox', { name: 'FEN / PGN', exact: true }).fill(live.moves[0].fen);
  const imported = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/games',
  );
  await page.getByRole('button', { name: 'Load position', exact: true }).click();
  const analysis = await (await imported).json();
  await expect(page.getByText('Free analysis', { exact: true })).toBeVisible();
  await page.waitForTimeout(1200);
  expect(count(analysis.id), 'An imported analysis position must never request a computer turn').toBe(0);
  expect((await gameState(page, analysis.id)).moves).toHaveLength(0);
  expect((await gameState(page, game.id)).moves).toHaveLength(4);
});

test('black receives one opening and one reply, cancels a pending navigation timer, and toggles persistent theme', async ({
  page,
}, info) => {
  const count = trackComputerCalls(page);
  const headers = await createProfile(page);
  const game = await start(page, 'black');
  // Leaving immediately must cancel a scheduled opening move until the game is resumed.
  await page.getByRole('link', { name: 'Game history', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(1);
  await page.waitForTimeout(1200);
  expect(count(game.id)).toBe(0);
  expect((await gameState(page, game.id)).moves).toHaveLength(0);
  await page.locator('.history-row').first().click();
  await expect.poll(async () => (await gameState(page, game.id)).moves.length).toBe(1);
  await expect(page.getByText('Your turn', { exact: true })).toBeVisible();
  expect(count(game.id)).toBe(1);
  await move(page, 'e7', 'e5');
  await expect.poll(async () => (await gameState(page, game.id)).moves.length).toBe(3);
  await expect(page.getByText('Your turn', { exact: true })).toBeVisible();
  expect(count(game.id)).toBe(2);
  const state = await gameState(page, game.id);
  expect(state.player_color).toBe('black');
  expect(state.moves.map((record: { source: string }) => record.source)).toEqual(['computer', 'player', 'computer']);
  expect(state.moves[1].uci).toBe('e7e5');

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  const light = await page.locator('html').evaluate((element) => getComputedStyle(element).backgroundColor);
  const darkToggle = page.getByRole('button', {
    name: 'Switch to dark theme',
    exact: true,
  });
  await expect(darkToggle).toBeVisible();
  await darkToggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect
    .poll(async () => (await (await page.request.get('/api/settings', { headers })).json()).theme)
    .toBe('dark');
  const dark = await page.locator('html').evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(dark).not.toBe(light);
  await mkdir('/tmp/chessmate-deployment', { recursive: true });
  await page.screenshot({
    path: `/tmp/chessmate-deployment/automatic-${info.project.name}-dark.png`,
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByRole('button', { name: 'Switch to light theme', exact: true })).toBeVisible();
  expect(count(game.id)).toBe(2);
  expect((await gameState(page, game.id)).moves).toHaveLength(3);
  await page.getByRole('button', { name: 'Switch to light theme', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect
    .poll(async () => (await (await page.request.get('/api/settings', { headers })).json()).theme)
    .toBe('light');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  expect(count(game.id)).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
