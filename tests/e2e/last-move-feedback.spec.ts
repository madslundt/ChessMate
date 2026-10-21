import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';
import { defaults, type Game } from '../../src/frontend/src/types';

test('both sides keep readable move feedback below the board across moves, tabs and history', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  const chess = new Chess();
  const initialFen = chess.fen();
  const moves = ['e4', 'e5', 'Nf3'].map((san, index) => {
    const before = chess.fen();
    const played = chess.move(san);
    return { uci: played.from + played.to, san, before_fen: before, fen: chess.fen(),
      feedback: { classification: ['Good', 'Blunder', 'Excellent'][index], text: [
        'White takes space in the center.', 'Black overlooks a tactical threat.', 'White develops the knight toward the center.',
      ][index] } };
  });
  Object.assign(moves[1].feedback, {
    text: 'The engine preferred c5 instead.',
    consequence: 'Black overlooks a tactical threat.',
  });
  let game: Game = { id: 'last-feedback', initial_fen: initialFen, fen: moves[1].fen, moves: moves.slice(0, 2), revision: 2,
    mode: 'training', player_color: 'white', difficulty: 2, status: 'playing', result: '*' };
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (pathname === '/api/profiles') body = [{ id: 'feedback-profile', name: 'Feedback test', preferences: {
      ...defaults, coaching_mode: 'independent', play_mode: 'coach_first', auto_computer: false,
      show_alternatives: false, theme: 'light',
    } }];
    else if (pathname === '/api/games/last-feedback/moves') {
      expect(route.request().postDataJSON().move).toBe('g1f3');
      game = { ...game, moves, fen: moves[2].fen, revision: 3 };
      body = game;
    } else if (pathname === '/api/games/last-feedback') body = game;
    else if (pathname === '/api/analysis') body = { fen: route.request().postDataJSON().fen, candidates: [] };
    else if (pathname.endsWith('/conversation')) body = { messages: [] };
    await route.fulfill({ json: body });
  });
  await page.addInitScript(() => localStorage.setItem('chessmate.profile', 'feedback-profile'));
  await page.goto('/play/last-feedback');
  const feedback = page.getByRole('region', { name: 'Last move feedback', exact: true });
  const white = feedback.getByRole('article', { name: 'White', exact: true });
  const black = feedback.getByRole('article', { name: 'Black', exact: true });
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe('/play/last-feedback');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await expect(white).toContainText('1. e4');
  await expect(white).toContainText('White takes space in the center.');
  await expect(black).toContainText('1... e5');
  await expect(black).toContainText('Black overlooks a tactical threat.');
  await expect(black).not.toContainText('The engine preferred');
  const coachFeedback = page.locator('.move-feedback-entry.black');
  await expect(coachFeedback).toContainText('Black overlooks a tactical threat.');
  await expect(coachFeedback).not.toContainText('The engine preferred');
  await coachFeedback.getByRole('button', { name: 'Why was it bad?', exact: true }).click();
  await expect(coachFeedback.locator('.move-feedback-explanation')).toHaveText('Black overlooks a tactical threat.');
  await expect(white).toHaveCSS('border-left-color', 'rgb(40, 112, 71)');
  await expect(black).toHaveCSS('border-left-color', 'rgb(165, 65, 60)');
  const boardBounds = await page.getByTestId('chessboard').boundingBox();
  const feedbackBounds = await feedback.boundingBox();
  expect(feedbackBounds!.y).toBeGreaterThanOrEqual(boardBounds!.y + boardBounds!.height);
  await page.getByRole('button', { name: /^Moves/ }).click();
  await expect(white).toBeVisible();
  await expect(black).toBeVisible();
  for (const square of ['g1', 'f3']) {
    const target = page.locator(`[data-square="${square}"]`);
    if (info.project.name === 'desktop') await target.click();
    else await target.tap();
  }
  await expect(white).toContainText('2. Nf3');
  await expect(white).toContainText('Excellent');
  await expect(black).toContainText('1... e5');
  await page.getByRole('button', { name: 'Flip board', exact: true }).click();
  await expect(white).toContainText('2. Nf3');
  await page.getByRole('button', { name: 'Previous move', exact: true }).click();
  await expect(white).toContainText('1. e4');
  await page.getByRole('button', { name: 'Starting position', exact: true }).click();
  await expect(white).toContainText('No moves yet.');
  await expect(black).toContainText('No moves yet.');
  await page.getByRole('button', { name: 'Latest position', exact: true }).click();
  await expect(white).toContainText('2. Nf3');
  await expect(black).toContainText('Black overlooks a tactical threat.');
  await feedback.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `/tmp/chessmate-last-feedback-${info.project.name}-light.png`, fullPage: true });
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
  await expect(white).toHaveCSS('border-left-color', 'rgb(139, 206, 163)');
  await expect(black).toHaveCSS('border-left-color', 'rgb(244, 163, 156)');
  await feedback.screenshot({ path: `/tmp/chessmate-last-feedback-${info.project.name}-dark.png` });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
