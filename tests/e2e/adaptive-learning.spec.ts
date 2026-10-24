import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import type { Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

test.use({ actionTimeout: 10000 });

const mate = '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1';

async function profile(page: Page, extra = {}) {
  const created = await page.request.post('/api/profiles', { data: { name: `adaptive_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` } });
  expect(created.status()).toBe(201);
  const user = await created.json(), headers = { 'X-Profile-ID': user.id };
  expect((await page.request.patch('/api/settings', { headers, data: { timezone: 'UTC', auto_computer: false, coaching_mode: 'independent', ...extra } })).status()).toBe(200);
  await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), user.id);
  return headers;
}

test.afterEach(async ({ page }) => {
  const id = await page.evaluate(() => localStorage.getItem('chessmate.profile'));
  if (id) await page.request.delete(`/api/profiles/${id}`);
});

test('new games default to adaptive and preserve a manual override', async ({ page }) => {
  const headers = await profile(page);
  await page.goto('/play');
  await expect(page).toHaveTitle(/Chessmate/);
  await page.getByRole('button', { name: 'New game', exact: true }).click();
  await expect(page.getByLabel('Computer difficulty', { exact: true })).toHaveValue('adaptive');
  await expect(page.getByRole('slider')).toHaveCount(0);
  await page.getByRole('button', { name: 'Start game', exact: true }).click();
  await expect(page.getByTestId('chessboard')).toBeVisible();
  await expect.poll(async () => (await (await page.request.get('/api/games', { headers })).json()).length).toBe(1);
  let games = await (await page.request.get('/api/games', { headers })).json();
  expect(games[0].difficulty_mode).toBe('adaptive');
  expect(games[0].difficulty).toBe(1);
  await page.getByRole('button', { name: 'New game', exact: true }).click();
  await page.getByLabel('Computer difficulty', { exact: true }).selectOption('manual');
  await page.getByRole('slider').fill('4');
  await page.getByRole('button', { name: 'Start game', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/api/games', { headers })).json()).length).toBe(2);
  games = await (await page.request.get('/api/games', { headers })).json();
  expect(games[0].difficulty_mode).toBe('manual');
  expect(games[0].difficulty).toBe(4);
});

test('independent play suppresses enabled evaluations and records an unaided decision', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const headers = await profile(page, {
    coaching_mode: 'guided', play_mode: 'independent', show_evaluation: true, show_evaluation_bar: true,
  });
  const game = await (await page.request.post('/api/games', { headers, data: { mode: 'computer', fen: mate } })).json();
  const analysisRequests: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/analysis') analysisRequests.push(request.url());
  });
  await page.goto(`/play/${game.id}`);
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page.getByLabel('Play mode', { exact: true })).toHaveValue('independent');
  await expect(page.locator('.evaluation-bar')).toHaveCount(0);
  await expect(page.locator('.position-evaluation')).toHaveCount(0);
  for (const square of ['f7', 'g7']) {
    const button = page.getByTestId('chessboard').locator(`[data-square="${square}"]`);
    if (info.project.name === 'desktop') await button.click();
    else await button.tap();
  }
  await expect.poll(async () => (await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json()).status).toBe('completed');
  const state = await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json();
  expect(state.evidence.independent_assessed).toBe(1);
  expect(analysisRequests).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `/tmp/chessmate-independent-evaluation-${info.project.name}.png`, fullPage: true });
});

test('automatic evaluation is explained in the Danish diary without a hint request', async ({ page }, info) => {
  const headers = await profile(page, {
    language: 'da', coach_language: 'da', show_evaluation: true, show_evaluation_bar: true,
  });
  const game = await (await page.request.post('/api/games', { headers, data: { mode: 'computer', fen: mate } })).json();
  const hintRequests: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/hint') hintRequests.push(request.url());
  });
  const evaluated = page.waitForResponse(response => new URL(response.url()).pathname === '/api/analysis'
    && response.request().postDataJSON()?.game_id === game.id && response.status() === 200);
  await page.goto(`/play/${game.id}`);
  await evaluated;
  await expect(page.locator('.position-evaluation')).toBeVisible();
  for (const square of ['f7', 'g7']) {
    const button = page.getByTestId('chessboard').locator(`[data-square="${square}"]`);
    if (info.project.name === 'desktop') await button.click();
    else await button.tap();
  }
  await expect.poll(async () => (await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json()).status).toBe('completed');
  const learning = await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json();
  await page.goto('/diary');
  const day = learning.completed_at.slice(0, 10);
  await page.getByLabel('Måned', { exact: true }).fill(day.slice(0, 7));
  await page.getByRole('button', { name: `${day}: 1 partier`, exact: true }).click();
  await expect(page.locator('.diary-detail')).toContainText('Beslutninger med motoranalyse: 1');
  await expect(page.locator('.diary-detail')).toContainText('selv uden hints');
  expect(hintRequests).toEqual([]);
  await page.screenshot({ path: `/tmp/chessmate-diary-evaluation-${info.project.name}.png`, fullPage: true });
});

test('finished game automatically appears in diary, calendar and saved range report', async ({ page }, info) => {
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('console', message => { if (message.type() === 'error') failures.push(message.text()); });
  const headers = await profile(page, { theme: info.project.name === 'mobile' ? 'dark' : 'light' });
  const created = await page.request.post('/api/games', { headers, data: { mode: 'computer', fen: mate } });
  expect(created.status()).toBe(201);
  const game = await created.json();
  await page.goto(`/play/${game.id}`);
  const board = page.getByTestId('chessboard');
  for (const square of ['f7', 'g7']) {
    const button = board.locator(`[data-square="${square}"]`);
    if (info.project.name === 'mobile' || info.project.name === 'tablet') await button.tap();
    else await button.click();
  }
  await expect(board.getByRole('heading', { name: 'Victory', exact: true })).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json()).status, { timeout: 30000 }).toBe('completed');
  const state = await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json();
  const day = state.completed_at.slice(0, 10), month = day.slice(0, 7);
  await page.getByRole('link', { name: 'Diary', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Diary', exact: true })).toBeVisible();
  await page.getByLabel('Month', { exact: true }).fill(month);
  const active = page.getByRole('button', { name: `${day}: 1 games`, exact: true });
  await expect(active).toBeEnabled();
  await active.focus();
  await active.press('Enter');
  await expect(page.locator('.diary-detail')).toContainText('Analysis complete');
  await expect(page.locator('.diary-detail')).toContainText('You completed 1 game');
  await expect(page.locator('.diary-assistance').first()).toContainText('Independent decisions: 1');
  await page.getByLabel('Month', { exact: true }).fill('2025-12');
  await page.getByRole('button', { name: 'Next month', exact: true }).click();
  await expect(page.getByLabel('Month', { exact: true })).toHaveValue('2026-01');
  await expect(page.locator('.diary-date.has-activity')).toHaveCount(0);
  await page.getByLabel('Month', { exact: true }).fill(month);
  await expect(active).toBeEnabled();
  await page.getByLabel('From', { exact: true }).fill(day);
  await page.getByLabel('To', { exact: true }).fill(day);
  await page.getByRole('button', { name: 'Generate report', exact: true }).click();
  await expect(page.locator('.diary-report-detail')).toContainText('You completed 1 game');
  await page.getByText('Saved reports', { exact: true }).click();
  await page.locator('.diary-saved-reports button').first().click();
  await expect(page.locator('.diary-report-detail')).toContainText('Analysis complete');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: `/tmp/chessmate-adaptive-diary-${info.project.name}.png`, fullPage: true });
  const position = page.locator('.diary-detail .diary-observations a').first();
  await expect(position).toHaveAttribute('href', `/analyze/${game.id}?ply=0`);
  await position.click();
  await expect(page).toHaveURL(new RegExp(`/analyze/${game.id}\\?ply=0$`));
  await expect(page.getByTestId('chessboard').getByRole('button', { name: 'f7 White q', exact: true })).toBeVisible();
  expect(failures).toEqual([]);
});

test('blind realistic training starts a legal game that can continue', async ({ page }, info) => {
  const headers = await profile(page);
  await page.goto('/learn');
  const training = page.locator('.realistic-training');
  await expect(training.getByRole('heading', { name: 'Play from a real position' })).toBeVisible();
  await training.getByLabel('Game mode', { exact: true }).selectOption('blind');
  await training.getByRole('button', { name: 'Continue this position', exact: true }).click();
  await expect(page.getByTestId('chessboard')).toBeVisible();
  await expect(page).toHaveURL(/\/play\/[\w-]+$/);
  let game = (await (await page.request.get('/api/games', { headers })).json())[0];
  expect(game.learning_source).toBe('training');
  expect(game.training_context.blind).toBe(true);
  expect(game.training_context.focus).toBeUndefined();
  expect(game.moves).toHaveLength(0);
  const move = game.legal_moves[0];
  for (const square of [move.slice(0, 2), move.slice(2, 4)]) {
    const button = page.getByTestId('chessboard').locator(`[data-square="${square}"]`);
    if (info.project.name === 'mobile' || info.project.name === 'tablet') await button.tap();
    else await button.click();
  }
  await expect.poll(async () => (await (await page.request.get(`/api/games/${game.id}`, { headers })).json()).moves.length).toBe(1);
  game = await (await page.request.get(`/api/games/${game.id}`, { headers })).json();
  const reply = await page.request.post(`/api/games/${game.id}/computer`, { headers, data: { revision: game.revision } });
  expect(reply.status()).toBe(200);
  expect((await reply.json()).moves).toHaveLength(2);
});

test('first hint saves the unsaved game and later destination help remains assisted', async ({ page }, info) => {
  const headers = await profile(page);
  await page.goto('/play');
  const hintRequests: Record<string, unknown>[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/hint') hintRequests.push(request.postDataJSON());
  });
  await page.getByRole('button', { name: 'Give me a hint', exact: true }).click();
  await expect(page.getByTestId('position-hint')).toBeVisible();
  expect(hintRequests).toHaveLength(1);
  expect(hintRequests[0].game_id).toBeTruthy();
  const identifier = hintRequests[0].game_id as string;
  await page.getByRole('button', { name: /^Next hint/ }).click();
  await expect.poll(() => hintRequests.length).toBe(2);
  const hint = page.getByTestId('position-hint');
  await expect(hint).toContainText('2/2');
  const records = await (await page.request.get('/api/games', { headers })).json();
  expect(records).toHaveLength(1);
  const game = await (await page.request.get(`/api/games/${identifier}`, { headers })).json();
  const move = game.legal_moves[0];
  for (const square of [move.slice(0, 2), move.slice(2, 4)]) {
    const button = page.getByTestId('chessboard').locator(`[data-square="${square}"]`);
    if (info.project.name === 'mobile' || info.project.name === 'tablet') await button.tap();
    else await button.click();
  }
  await expect.poll(async () => (await (await page.request.get(`/api/games/${identifier}`, { headers })).json()).moves.length).toBe(1);
  const moved = await (await page.request.get(`/api/games/${identifier}`, { headers })).json();
  expect(moved.moves[0].assistance.category).toBe('destination_revealed');
  expect(moved.moves[0].assistance.event_ids.length).toBeGreaterThanOrEqual(2);
});

test('Danish diary navigates an empty historical month and saves an empty report', async ({ page }, info) => {
  const headers = await profile(page, { language: 'da', coach_language: 'da', theme: 'dark' });
  await page.goto('/diary');
  await expect(page.getByRole('heading', { name: 'Dagbog', exact: true })).toBeVisible();
  await page.getByLabel('Måned', { exact: true }).fill('2000-01');
  await page.locator('.diary-month-nav').getByRole('button', { name: 'Forrige måned', exact: true }).click();
  await expect(page.getByLabel('Måned', { exact: true })).toHaveValue('1999-12');
  await expect(page.getByRole('button', { name: '1999-12-31: 0 partier', exact: true })).toBeDisabled();
  await expect(page.locator('.diary-date.has-activity')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Vælg en dag', exact: true })).toBeVisible();
  await page.getByLabel('Fra', { exact: true }).fill('1999-12-01');
  await page.getByLabel('Til', { exact: true }).fill('1999-12-31');
  await page.getByRole('button', { name: 'Lav rapport', exact: true }).click();
  await expect(page.locator('.diary-report-detail')).toContainText('Du afsluttede 0 partier');
  const reports = await (await page.request.get('/api/diary/reports', { headers })).json();
  expect(reports).toHaveLength(1);
  expect(reports[0].statistics.games).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: `/tmp/chessmate-danish-diary-${info.project.name}.png`, fullPage: true });
});

test('resignation and a completed nonterminal PGN feed the same daily diary', async ({ page }, info) => {
  const headers = await profile(page);
  await page.goto('/play');
  await page.getByRole('button', { name: 'New game', exact: true }).click();
  await page.getByRole('button', { name: 'Start game', exact: true }).click();
  const board = page.getByTestId('chessboard');
  for (const square of ['e2', 'e4']) {
    const target = board.locator(`[data-square="${square}"]`);
    if (info.project.name === 'desktop') await target.click();
    else await target.tap();
  }
  await expect(page.getByRole('button', { name: 'Resign', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Resign', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Game finished', exact: true }).getByRole('heading', { name: 'Defeat', exact: true })).toBeVisible();
  const resigned = (await (await page.request.get('/api/games', { headers })).json())[0];
  expect(resigned.status).toBe('resignation');
  expect(resigned.result).toBe('0-1');
  const imported = await page.request.post('/api/games', { headers, data: {
    mode: 'computer', player_color: 'white', pgn: '[Result "1-0"]\n\n1. e4 e5 1-0',
  } });
  expect(imported.status()).toBe(201);
  const game = await imported.json();
  expect(game.status).toBe('imported_result');
  expect(game.result).toBe('1-0');
  expect(game.moves).toHaveLength(2);
  expect((await page.request.post(`/api/games/${game.id}/moves`, { headers, data: { revision: game.revision, move: 'Nf3' } })).status()).toBe(409);
  for (const identifier of [resigned.id, game.id]) {
    await expect.poll(async () => (await (await page.request.get(`/api/games/${identifier}/learning`, { headers })).json()).status, { timeout: 30000 }).toBe('completed');
  }
  const learning = await (await page.request.get(`/api/games/${game.id}/learning`, { headers })).json();
  expect(learning.evidence.observations.every((item: { assistance: string }) => item.assistance === 'unknown')).toBe(true);
  expect(learning.evidence.independent_assessed).toBe(0);
  await page.goto(`/play/${game.id}`);
  await expect(page.getByRole('region', { name: 'Game finished', exact: true }).getByRole('heading', { name: 'Victory', exact: true })).toBeVisible();
  const day = learning.completed_at.slice(0, 10);
  const diary = await (await page.request.get(`/api/diary/days/${day}`, { headers })).json();
  expect(diary.statistics.games).toBe(2);
  expect(diary.statistics.wins).toBe(1);
  expect(diary.statistics.losses).toBe(1);
  expect(diary.statistics.unknown).toBeGreaterThan(0);
  expect(diary.source_statistics.game.games).toBe(1);
  expect(diary.source_statistics.import.games).toBe(1);
  await page.getByRole('link', { name: 'Diary', exact: true }).first().click();
  await page.getByLabel('Month', { exact: true }).fill(day.slice(0, 7));
  await page.getByRole('button', { name: `${day}: 2 games`, exact: true }).click();
  const sources = page.locator('.diary-detail .diary-source-evidence');
  await expect(sources).toContainText('Complete games');
  await expect(sources).toContainText('Imported games');
  await expect(sources.locator('article').filter({ hasText: 'Imported games' })).toContainText('Independent decisions: 0');
});
