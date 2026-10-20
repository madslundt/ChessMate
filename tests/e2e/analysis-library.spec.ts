import { test, expect, type Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';
import { defaults, type Game } from '../../src/frontend/src/types';

function savedGame(id: string, mode: Game['mode'], sans: string[], initialFen?: string): Game {
  const chess = new Chess(initialFen);
  const initial_fen = chess.fen();
  const moves = sans.map((san) => {
    const before_fen = chess.fen();
    const move = chess.move(san);
    return { uci: `${move.from}${move.to}`, san: move.san, fen: chess.fen(), before_fen, feedback: null };
  });
  return {
    id, mode, moves, initial_fen, fen: chess.fen(), revision: moves.length,
    player_color: 'white', difficulty: 2, created_at: '2026-10-20T12:00:00Z',
    status: chess.isCheckmate() ? 'checkmate' : 'active', result: chess.isCheckmate() ? '0-1' : '*',
  };
}

async function library(page: Page, empty = false) {
  const state = {
    games: empty ? [] : [
      savedGame('finished-training', 'training', ['f3', 'e5', 'g4', 'Qh4#']),
      savedGame('active-computer', 'computer', ['e4', 'e5']),
      savedGame('imported-analysis', 'analysis', ['d4', 'd5', 'c4']),
    ],
    failList: false,
    imports: [] as Record<string, unknown>[],
    mutations: [] as string[],
    unexpected: [] as string[],
  };
  await page.addInitScript(() => localStorage.setItem('chessmate.profile', 'library-profile'));
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/profiles') {
      await route.fulfill({ json: [{
        id: 'library-profile', name: 'Game learner',
        preferences: { ...defaults, coaching_mode: 'independent', auto_computer: false },
      }] });
      return;
    }
    if (path === '/api/games' && request.method() === 'GET') {
      await route.fulfill(state.failList
        ? { status: 503, json: { detail: 'Saved games are temporarily unavailable.' } }
        : { json: state.games });
      return;
    }
    if (path === '/api/games' && request.method() === 'POST') {
      const body = request.postDataJSON();
      state.imports.push(body);
      const game = savedGame('new-import', 'analysis', [], body.fen);
      state.games.push(game);
      await route.fulfill({ status: 201, json: game });
      return;
    }
    const game = state.games.find((item) => path.startsWith(`/api/games/${item.id}`));
    if (game && request.method() === 'GET') {
      if (path === `/api/games/${game.id}`) {
        await route.fulfill({ json: game });
        return;
      }
      if (path === `/api/games/${game.id}/conversation`) {
        await route.fulfill({ json: { messages: [] } });
        return;
      }
      if (path === `/api/games/${game.id}/review`) {
        await route.fulfill({ json: { summary: 'Review this saved game.', positives: [], mistakes: [], topics: [] } });
        return;
      }
    }
    if (path === '/api/analysis') {
      await route.fulfill({ json: { fen: request.postDataJSON().fen, candidates: [] } });
      return;
    }
    if (path.startsWith('/api/games') && request.method() !== 'GET') {
      state.mutations.push(`${request.method()} ${path}`);
    }
    state.unexpected.push(`${request.method()} ${path}`);
    await route.fulfill({ status: 500, json: { detail: 'Unexpected request in analysis library test' } });
  });
  return state;
}

test('Analyze lists every saved game and opens each game in its own review workspace', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  const state = await library(page);
  await page.goto('/analyze');
  await expect(page.getByRole('heading', { name: 'Analyze', exact: true })).toBeVisible();
  await expect(page.getByText('Choose a game to review its moves and learn from your decisions.', { exact: true })).toBeVisible();
  await expect(page.getByTestId('chessboard')).toHaveCount(0);
  await expect(page.locator('.history-row')).toHaveCount(3);
  for (const game of state.games) {
    await expect(page.locator(`.history-row[href="/analyze/${game.id}"]`)).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `/tmp/chessmate-analysis-library-${info.project.name}.png`, fullPage: true });

  await page.locator('.history-row[href="/analyze/finished-training"]').click();
  await expect(page).toHaveURL('/analyze/finished-training');
  await expect(page.getByTestId('chessboard')).toBeVisible();
  await expect(page.locator('[data-square="h4"] [data-piece="bQ"]')).toHaveCount(1);
  await expect(page.getByRole('tab', { name: 'Review game', exact: true })).toHaveAttribute('aria-selected', 'true');
  const back = page.getByRole('link', { name: 'Back to games', exact: true });
  await expect(back).toHaveAttribute('href', '/analyze');
  await back.click();
  await expect(page).toHaveURL('/analyze');
  await expect(page.getByTestId('chessboard')).toHaveCount(0);

  await page.locator('.history-row[href="/analyze/active-computer"]').click();
  await expect(page).toHaveURL('/analyze/active-computer');
  await expect(page.locator('[data-square="e4"] [data-piece="wP"]')).toHaveCount(1);
  const analyze = page.getByRole('link', { name: 'Analyze', exact: true });
  await expect(analyze).toHaveAttribute('href', '/analyze');
  await analyze.click();
  await expect(page).toHaveURL('/analyze');
  await expect(page.locator('.history-row')).toHaveCount(3);

  await page.locator('.history-row[href="/analyze/imported-analysis"]').click();
  await expect(page).toHaveURL('/analyze/imported-analysis');
  await expect(page.locator('[data-square="c4"] [data-piece="wP"]')).toHaveCount(1);
  await page.goBack();
  await expect(page).toHaveURL('/analyze');
  await expect(page.locator('.history-row')).toHaveCount(3);
  await page.goForward();
  await expect(page).toHaveURL('/analyze/imported-analysis');
  await page.reload();
  await expect(page).toHaveURL('/analyze/imported-analysis');
  await expect(page.locator('[data-square="c4"] [data-piece="wP"]')).toHaveCount(1);
  await expect(analyze).toHaveAttribute('href', '/analyze');
  expect(state.imports).toEqual([]);
  expect(state.mutations).toEqual([]);
  expect(state.unexpected).toEqual([]);
  expect(errors).toEqual([]);
});

test('empty Analyze library offers playing a game and importing a position', async ({ page }) => {
  const state = await library(page, true);
  await page.goto('/analyze');
  await expect(page.getByText('Play a game or import one to start analyzing.', { exact: true })).toBeVisible();
  await expect(page.getByTestId('chessboard')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Import FEN / PGN', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Play game', exact: true }).click();
  await expect(page).toHaveURL('/play');
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Analyze', exact: true }).click();
  await expect(page).toHaveURL('/analyze');
  await expect(page.getByTestId('chessboard')).toHaveCount(0);
  expect(state.imports).toEqual([]);
  expect(state.unexpected).toEqual([]);
});

test('Analyze library retries a failed games request without showing an empty library', async ({ page }) => {
  const state = await library(page);
  state.failList = true;
  await page.goto('/analyze');
  await expect(page.getByRole('alert')).toContainText('Saved games are temporarily unavailable.');
  await expect(page.getByText('Play a game or import one to start analyzing.', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('chessboard')).toHaveCount(0);
  state.failList = false;
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(3);
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(state.unexpected).toEqual([]);
});

test('Analyze library imports a position directly and adds it to the game list', async ({ page }) => {
  const state = await library(page, true);
  await page.goto('/analyze');
  await page.getByRole('button', { name: 'Import FEN / PGN', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Import FEN / PGN', exact: true });
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('chessboard')).toHaveCount(0);
  const fen = '7k/P7/8/8/8/8/8/7K w - - 0 1';
  await dialog.getByRole('textbox', { name: 'FEN / PGN', exact: true }).fill(fen);
  await dialog.getByRole('button', { name: 'Load position', exact: true }).click();
  await expect(page).toHaveURL('/analyze/new-import');
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('[data-square="a7"] [data-piece="wP"]')).toHaveCount(1);
  expect(state.imports).toEqual([expect.objectContaining({ mode: 'analysis', fen })]);
  await page.getByRole('link', { name: 'Back to games', exact: true }).click();
  await expect(page).toHaveURL('/analyze');
  await expect(page.locator('.history-row[href="/analyze/new-import"]')).toBeVisible();
  expect(state.mutations).toEqual([]);
  expect(state.unexpected).toEqual([]);
});
