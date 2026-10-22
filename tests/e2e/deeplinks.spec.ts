import { test, expect, type Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import type { Exercise, Game } from '../../src/frontend/src/types';
import { defaults } from '../../src/frontend/src/types';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';

const createdProfiles = new WeakMap<Page, string>();

async function createProfile(page: Page) {
  const response = await page.request.post('/api/profiles', {
    data: { name: `links_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` },
  });
  expect(response.status()).toBe(201);
  const profile = await response.json();
  createdProfiles.set(page, profile.id);
  const headers = { 'X-Profile-ID': profile.id as string };
  const settings = await page.request.patch('/api/settings', {
    headers,
    data: { auto_computer: false, coaching_mode: 'independent', feedback: 'none' },
  });
  expect(settings.status()).toBe(200);
  return { profile, headers };
}

async function selectProfile(page: Page, id: string) {
  await page.addInitScript((profileId) => localStorage.setItem('chessmate.profile', profileId), id);
}

test.afterEach(async ({ page }) => {
  const profileId = createdProfiles.get(page);
  if (profileId) await page.request.delete(`/api/profiles/${profileId}`);
});

async function move(page: Page, from: string, to: string) {
  const touch = await page.evaluate(() => navigator.maxTouchPoints > 0);
  for (const square of [from, to]) {
    const target = page.locator(`[data-square="${square}"]`);
    if (touch) await target.tap();
    else await target.click();
  }
}

async function start(page: Page): Promise<Game> {
  await page.getByRole('button', { name: 'New game', exact: true }).click();
  const created = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/games',
  );
  await page.getByRole('button', { name: 'Start game', exact: true }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  return response.json();
}

test('first move creates one game link and refresh restores the saved position', async ({ page }, info) => {
  const { profile, headers } = await createProfile(page);
  await selectProfile(page, profile.id);
  await page.goto('/play');
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  const created = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/games',
  );
  const moved = page.waitForResponse(
    (response) => response.request().method() === 'POST' && /\/api\/games\/[^/]+\/moves$/.test(new URL(response.url()).pathname),
  );
  await move(page, 'e2', 'e4');
  expect((await moved).status()).toBe(200);
  const game: Game = await (await created).json();
  await expect(page).toHaveURL(`/play/${game.id}`);
  await expect(page.getByText('Automatically saved', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(`/play/${game.id}`);
  await expect(page.locator('[data-square="e4"] [data-piece="wP"]')).toHaveCount(1);
  const games = await (await page.request.get('/api/games', { headers })).json();
  expect(games).toHaveLength(1);
  expect(games[0].moves.map((m: { uci: string }) => m.uci)).toEqual(['e2e4']);
  await page.screenshot({ path: `/tmp/chessmate-deeplinks-${info.project.name}.png`, fullPage: true });
});

test('Start game creates unique links immediately and URL takes precedence over the old saved game', async ({ page }) => {
  const { profile, headers } = await createProfile(page);
  await selectProfile(page, profile.id);
  await page.goto('/play');
  const first = await start(page);
  await expect(page).toHaveURL(`/play/${first.id}`);
  expect(first.moves).toHaveLength(0);
  await page.reload();
  await expect(page.getByText('Automatically saved', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(`/play/${first.id}`);
  const second = await start(page);
  expect(second.id).not.toBe(first.id);
  await expect(page).toHaveURL(`/play/${second.id}`);
  expect(second.moves).toHaveLength(0);
  await move(page, 'd2', 'd4');
  await expect.poll(async () =>
    (await (await page.request.get(`/api/games/${second.id}`, { headers })).json()).moves.length,
  ).toBe(1);
  await page.evaluate((id) => localStorage.setItem('chessmate.game', id), second.id);
  await page.goto(`/play/${first.id}`);
  await expect(page.getByText('Automatically saved', { exact: true })).toBeVisible();
  await expect(page.locator('[data-square="d2"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="d4"] [data-piece="wP"]')).toHaveCount(0);
  await page.goto(`/play/${second.id}`);
  await expect(page.locator('[data-square="d4"] [data-piece="wP"]')).toHaveCount(1);
  await page.goto('/play');
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  await expect(page.locator('[data-square="d2"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.getByText('Automatically saved', { exact: true })).toHaveCount(0);
  expect((await (await page.request.get('/api/games', { headers })).json())).toHaveLength(2);
});

test('analysis links restore imported positions and survive profile selection', async ({ page }) => {
  const { profile, headers } = await createProfile(page);
  const response = await page.request.post('/api/games', {
    headers,
    data: { mode: 'analysis', fen: '7k/P7/8/8/8/8/8/7K w - - 0 1' },
  });
  expect(response.status()).toBe(201);
  const game: Game = await response.json();
  await page.goto(`/analyze/${game.id}`);
  await expect(page.getByRole('heading', { name: 'Choose a profile', exact: true })).toBeVisible();
  await page.getByRole('button', { name: profile.name, exact: true }).click();
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  await expect(page.getByText('Free analysis', { exact: true })).toBeVisible();
  await expect(page.locator('[data-square="a7"] [data-piece="wP"]')).toHaveCount(1);
  await page.reload();
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  await expect(page.locator('[data-square="a7"] [data-piece="wP"]')).toHaveCount(1);
});

test('main pages, categories and exercises support direct links and browser history', async ({ page }) => {
  const { profile, headers } = await createProfile(page);
  await selectProfile(page, profile.id);
  const exercises: Exercise[] = await (await page.request.get('/api/exercises?category=forks', { headers })).json();
  const exercise = exercises[0];
  expect(exercise).toBeTruthy();
  await page.goto('/play');
  for (const [name, path] of [
    ['Game history', '/history'], ['Progress', '/progress'], ['Settings', '/settings'], ['Learn', '/learn'],
  ]) {
    await page.getByRole('link', { name, exact: true }).click();
    await expect(page).toHaveURL(path);
    await page.reload();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  }
  await page.goBack();
  await expect(page).toHaveURL('/settings');
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL('/learn');
  await expect(page.getByRole('heading', { name: 'Learn', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Forks', exact: true }).click();
  await expect(page).toHaveURL('/learn/forks');
  await page.locator('.lesson-row').filter({ hasText: exercise.title }).click();
  const exercisePath = `/learn/forks/exercises/${exercise.id}`;
  await expect(page).toHaveURL(exercisePath);
  await expect(page.getByRole('heading', { name: exercise.title, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: exercise.title, exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL('/learn/forks');
  await expect(page.getByRole('tab', { name: 'Forks', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.goForward();
  await expect(page).toHaveURL(exercisePath);
  await expect(page.getByRole('heading', { name: exercise.title, exact: true })).toBeVisible();
  await page.goto('/learn/opening');
  await expect(page.getByRole('heading', { name: 'Your opening repertoire', exact: true })).toBeVisible();
});

test('practice queue survives reload through the session link', async ({ page }) => {
  const { profile } = await createProfile(page);
  await selectProfile(page, profile.id);
  await page.goto('/learn/forks');
  await page.getByRole('button', { name: 'Start practice · Forks', exact: true }).click();
  await expect(page).toHaveURL(/\/learn\/forks\/exercises\/[^/?]+\?session=[^/]+$/);
  const link = page.url();
  const title = await page.locator('.page-heading h1').innerText();
  await page.reload();
  await expect(page).toHaveURL(link);
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(page.locator('.page-heading')).toContainText('Your practice session');
});

test('missing game link shows an error and never creates a replacement game', async ({ page }) => {
  const { profile, headers } = await createProfile(page);
  await selectProfile(page, profile.id);
  const creations: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/games') creations.push(request.url());
  });
  await page.goto('/play/missing-game');
  await expect(page.getByRole('alert')).toContainText('Game not found');
  if (await page.getByTestId('chessboard').isVisible()) await move(page, 'e2', 'e4');
  await expect(page).toHaveURL('/play/missing-game');
  expect(creations).toEqual([]);
  expect((await (await page.request.get('/api/games', { headers })).json())).toHaveLength(0);
});

test('unknown pages and malformed subpages show a recoverable error', async ({ page }) => {
  const { profile } = await createProfile(page);
  await selectProfile(page, profile.id);
  for (const path of ['/unknown', '/learn/unknown', '/play/game/extra', '/play/game%2Fother']) {
    await page.goto(path);
    await expect(page.getByRole('alert')).toContainText('Page not found.');
    await expect(page.getByTestId('chessboard')).toHaveCount(0);
    await page.getByRole('link', { name: 'Learn', exact: true }).click();
    await expect(page).toHaveURL('/learn');
    await expect(page.getByRole('heading', { name: 'Learn', exact: true })).toBeVisible();
  }
});

// Keep the review classifications deterministic without requiring an engine or LLM.
async function reviewedGame(page: Page, playerColor: 'white' | 'black' = 'white', draw = false) {
  const chess = new Chess(draw ? '7k/8/8/8/8/8/8/K7 w - - 0 1' : undefined);
  const initialFen = chess.fen();
  const moves = draw ? [] : ['f3', 'e5', 'g4', 'Qh4#'].map((san, index) => {
    const beforeFen = chess.fen();
    const move = chess.move(san);
    const feedback = index === 0
      ? { classification: 'Good', text: 'A reviewed good decision.' }
      : index === 2
        ? { classification: 'Blunder', text: 'Check the threat to your king before advancing this pawn.' }
        : null;
    return {
      uci: `${move.from}${move.to}`,
      san: move.san,
      before_fen: beforeFen,
      fen: chess.fen(),
      color: index % 2 ? 'black' : 'white',
      feedback,
    };
  });
  const game: Game = {
    id: 'review-game', mode: 'training', player_color: playerColor, difficulty: 2,
    initial_fen: initialFen, fen: chess.fen(), moves, revision: moves.length,
    status: draw ? 'draw' : 'checkmate', result: draw ? '1/2-1/2' : '0-1',
  };
  const review = {
    game_id: game.id, revision: game.revision,
    summary: 'Review the threat before your second pawn move.',
    positives: moves.flatMap((m, i) => m.feedback?.classification === 'Good'
      ? [{ ply: i + 1, san: m.san, fen: m.before_fen, feedback: m.feedback }] : []),
    mistakes: moves.flatMap((m, i) => m.feedback?.classification === 'Blunder'
      ? [{ ply: i + 1, san: m.san, fen: m.before_fen, feedback: m.feedback }] : []),
    topics: ['opening'], result: game.result,
  };
  const coachRequests: Record<string, unknown>[] = [];
  const analysisRequests: Record<string, unknown>[] = [];
  const gameMutations: string[] = [];
  const unexpectedRequests: string[] = [];
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'GET' && path.startsWith('/api/games')) {
      gameMutations.push(`${request.method()} ${path}`);
    }
    let json: unknown;
    if (path === '/api/profiles') json = [{
      id: 'review-profile', name: 'Game reviewer',
      preferences: { ...defaults, auto_computer: false, coaching_mode: 'independent' },
    }];
    else if (path === `/api/games/${game.id}`) json = game;
    else if (path === `/api/games/${game.id}/review`) json = review;
    else if (path === `/api/games/${game.id}/learning`) json = { status: 'completed' };
    else if (path === `/api/games/${game.id}/conversation`) json = { messages: [] };
    else if (path === '/api/settings/speech') json = { stt_mode: 'browser', tts_mode: 'browser' };
    else if (path === '/api/analysis') {
      analysisRequests.push(request.postDataJSON());
      json = { fen: request.postDataJSON().fen, candidates: [] };
    }
    else if (path === '/api/coach') {
      coachRequests.push(request.postDataJSON());
      await route.fulfill({
        contentType: 'text/event-stream',
        body: 'event: done\ndata: {"text":"Look for the queen threat before moving your g-pawn.","source":"deterministic"}\n\n',
      });
      return;
    } else {
      unexpectedRequests.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 500, json: { detail: 'Unexpected request in review test' } });
      return;
    }
    await route.fulfill({ json });
  });
  await selectProfile(page, 'review-profile');
  return { game, review, coachRequests, analysisRequests, gameMutations, unexpectedRequests };
}

test('finished game shows counts and opens its classified review before chat', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  const { game, review, coachRequests, gameMutations, unexpectedRequests } = await reviewedGame(page);
  const savedGame = JSON.stringify(game);
  await page.goto(`/play/${game.id}`);
  const result = page.getByRole('region', { name: 'Game finished', exact: true });
  await expect(result.getByRole('heading', { name: 'Defeat', exact: true })).toBeVisible();
  for (const [label, count] of [['Best', 0], ['Excellent', 0], ['Good', 1], ['Inaccuracy', 0], ['Mistake', 0], ['Blunder', 1]] as const) {
    await expect(result.getByLabel(`${label}: ${count}`, { exact: true })).toBeVisible();
  }
  await expect(result.getByRole('link', { name: 'Analyze game', exact: true }))
    .toHaveAttribute('href', `/analyze/${game.id}`);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText(review.summary, { exact: true })).toHaveCount(0);
  await result.getByRole('link', { name: 'Analyze game', exact: true }).click();
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  const reviewTab = page.getByRole('tab', { name: 'Review game', exact: true });
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('textbox', { name: 'Ask about this position…', exact: true })).toHaveCount(0);
  const blunder = page.locator('.review-move').filter({ hasText: 'g4' });
  await expect(blunder).toBeVisible();
  await blunder.click();
  await expect(page.getByRole('button', { name: 'Reveal engine feedback', exact: true })).toBeVisible();
  await page.getByLabel('Your intended move', { exact: true }).fill('Check my king safety before advancing g4');
  await page.getByRole('button', { name: 'Reveal engine feedback', exact: true }).click();
  await expect(page.locator('.review-decision')).toContainText('Check the threat to your king');
  const filters = page.getByRole('group', { name: 'Review game', exact: true });
  const detail = page.locator('.review-decision');
  for (const label of ['Blunder · 1', 'All moves · 2']) {
    await filters.getByRole('button', { name: label, exact: true }).click();
    await expect(detail).toContainText('g4 · Blunder');
  }
  await filters.getByRole('button', { name: 'Good · 1', exact: true }).click();
  await expect(detail).toHaveCount(0);
  await expect(blunder).toHaveCount(0);
  await filters.getByRole('button', { name: 'All moves · 2', exact: true }).click();
  await expect(blunder).toBeVisible();
  await expect(detail).toHaveCount(0);
  await blunder.click();
  // A review starts before the decision so the player can inspect the threat.
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(0);
  await expect(page.locator('[data-square="e5"] [data-piece="bP"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'After move', exact: true }).click();
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Before move', exact: true }).click();
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Try an alternative', exact: true }).click();
  await expect(page.getByText('Exploring a variation', { exact: true })).toBeVisible();
  await move(page, 'g1', 'h3');
  await expect(page.locator('[data-square="h3"] [data-piece="wN"]')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Play first move', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Return to game', exact: true }).click();
  await expect(page.locator('[data-square="g1"] [data-piece="wN"]')).toHaveCount(1);
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  await page.getByRole('tab', { name: 'Chat', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ask about this position…', exact: true }).fill('Why was g4 a blunder?');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('.chat-message.assistant')).toContainText('Look for the queen threat');
  expect(coachRequests).toEqual([expect.objectContaining({
    game_id: game.id, fen: game.moves[2].before_fen, question: 'Why was g4 a blunder?', explore: false,
  })]);
  await reviewTab.click();
  await expect(blunder).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  await expect(reviewTab).toHaveAttribute('aria-selected', 'true');
  await expect(blunder).toBeVisible();
  await blunder.click();
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  // Reloading restores the original saved line after the temporary alternative.
  await page.getByRole('tab', { name: /^Moves/ }).click();
  await expect(page.locator('.move-table')).toContainText('g4');
  await expect(page.locator('.move-table')).not.toContainText('Nh3');
  await reviewTab.click();
  await blunder.click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `/tmp/chessmate-review-${info.project.name}.png`, fullPage: true });
  expect(gameMutations).toEqual([]);
  expect(JSON.stringify(game)).toBe(savedGame);
  expect(unexpectedRequests).toEqual([]);
  expect(errors).toEqual([]);
});

for (const outcome of [
  { color: 'black' as const, draw: false, heading: 'Victory' },
  { color: 'white' as const, draw: true, heading: 'Draw' },
]) {
  test(`finished game reports ${outcome.heading.toLowerCase()} from the player's perspective`, async ({ page }) => {
    const { game, unexpectedRequests } = await reviewedGame(page, outcome.color, outcome.draw);
    await page.goto(`/play/${game.id}`);
    await expect(page.getByRole('region', { name: 'Game finished', exact: true })
      .getByRole('heading', { name: outcome.heading, exact: true })).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(unexpectedRequests).toEqual([]);
  });
}

function betterMove(uci: string, san: string, cp: number, pv: string[] = []) {
  return { uci, san, cp, mate: null, pv: [san], pv_uci: pv.length ? pv : [uci],
    explanation: `Try ${san} to address the position's immediate threats.` };
}

test('blunder review explains the consequence and previews at most three better moves from before the decision', async ({ page }, info) => {
  const { game, analysisRequests, gameMutations, unexpectedRequests } = await reviewedGame(page);
  Object.assign(game.moves[2].feedback!, {
    consequence: 'Moving the g-pawn opens the queen diagonal to your king and allows Qh4 mate.',
    played: betterMove('g2g4', 'g4', -1000),
    alternatives: [
      betterMove('g2g4', 'g4', -1000),
      betterMove('d2d4', 'd4', 0, ['d2d4', 'e5d4']),
      betterMove('d2d4', 'd4', 0),
      betterMove('h2h4', 'h4', -2000),
      betterMove('e2e4', 'e4', -20),
      betterMove('g2g3', 'g3', -30),
      betterMove('b1c3', 'Nc3', -40),
    ],
  });
  const saved = JSON.stringify(game);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(`/analyze/${game.id}`);
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.locator('.review-move').filter({ hasText: 'g4' }).click();
  await page.getByRole('button', { name: 'Reveal engine feedback', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Why this was bad', exact: true })).toBeVisible();
  await expect(page.locator('.review-decision')).toContainText(String(game.moves[2].feedback?.consequence));
  await expect(page.getByRole('button', { name: /^Preview / })).toHaveCount(0);
  await page.getByRole('region', { name: 'Why this was bad', exact: true }).screenshot({ path: `/tmp/chessmate-bad-move-reason-${info.project.name}.png` });
  await page.getByRole('button', { name: 'Better moves', exact: true }).click();
  await expect(page.getByRole('button', { name: /^Preview / })).toHaveCount(3);
  for (const san of ['d4', 'e4', 'g3']) {
    await expect(page.getByRole('button', { name: `Preview ${san}`, exact: true })).toBeVisible();
  }
  for (const san of ['g4', 'h4', 'Nc3']) {
    await expect(page.getByRole('button', { name: `Preview ${san}`, exact: true })).toHaveCount(0);
  }
  expect(analysisRequests).toEqual([]);
  await page.getByRole('button', { name: 'After move', exact: true }).click();
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Preview d4', exact: true }).click();
  await expect(page.getByText('Exploring a variation', { exact: true })).toBeVisible();
  await expect(page.locator('[data-square="d4"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(0);
  await expect(page.locator('[data-square="e5"] [data-piece="bP"]')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Play first move', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Return to game', exact: true }).click();
  await page.getByRole('button', { name: 'Before move', exact: true }).click();
  await page.getByRole('region', { name: 'Why this was bad', exact: true })
    .evaluate((section) => section.scrollIntoView({ block: 'start', behavior: 'instant' }));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `/tmp/chessmate-blunder-${info.project.name}.png`, fullPage: true, animations: 'disabled' });
  expect(gameMutations).toEqual([]);
  expect(JSON.stringify(game)).toBe(saved);
  expect(unexpectedRequests).toEqual([]);
  expect(errors).toEqual([]);
});

test('older blunder feedback loads better moves for the position before the decision', async ({ page }) => {
  const { game, gameMutations, unexpectedRequests } = await reviewedGame(page);
  const requested: Record<string, unknown>[] = [];
  await page.route('**/api/analysis', async (route) => {
    requested.push(route.request().postDataJSON());
    await route.fulfill({ json: {
      fen: game.moves[2].before_fen,
      candidates: [betterMove('d2d4', 'd4', 0), betterMove('e2e4', 'e4', -20)],
    } });
  });
  await page.goto(`/analyze/${game.id}`);
  await page.locator('.review-move').filter({ hasText: 'g4' }).click();
  await page.getByRole('button', { name: 'Reveal engine feedback', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Why this was bad', exact: true })).toBeVisible();
  expect(requested).toEqual([]);
  await page.getByRole('button', { name: 'Better moves', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Preview d4', exact: true })).toBeVisible();
  // Without a recorded played score, only the top fresh candidate is confirmed.
  await expect(page.getByRole('button', { name: /^Preview / })).toHaveCount(1);
  expect(requested.length).toBeGreaterThan(0);
  for (const request of requested) {
    expect(request).toEqual(expect.objectContaining({ fen: game.moves[2].before_fen, candidates: 3 }));
  }
  expect(gameMutations).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
});

test('blunder explanation stays available when fresh better-move analysis fails', async ({ page }) => {
  const { game, gameMutations, unexpectedRequests } = await reviewedGame(page);
  await page.route('**/api/analysis', async (route) => {
    await route.fulfill({ status: 503, json: { detail: 'Analysis is temporarily unavailable.' } });
  });
  await page.goto(`/analyze/${game.id}`);
  await page.locator('.review-move').filter({ hasText: 'g4' }).click();
  await page.getByRole('button', { name: 'Reveal engine feedback', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Why this was bad', exact: true })).toBeVisible();
  await expect(page.locator('.review-decision')).toContainText('Check the threat to your king');
  await page.getByRole('button', { name: 'Better moves', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Analysis is temporarily unavailable.');
  await expect(page.getByRole('button', { name: /^Preview / })).toHaveCount(0);
  await page.getByRole('button', { name: 'After move', exact: true }).click();
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(1);
  expect(gameMutations).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
});
