import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';
import { defaults, type Color, type Game } from '../../src/frontend/src/types';

const positions = {
  white: { fen: '7k/5Q2/6K1/8/8/8/8/8 w - - 0 1', move: 'f7g7', score: '1-0' },
  black: { fen: '8/8/8/8/8/6k1/5q2/7K b - - 0 1', move: 'f2g2', score: '0-1' },
  draw: { fen: '7k/5K2/8/6Q1/8/8/8/8 w - - 0 1', move: 'g5g6', score: '1/2-1/2' },
};

for (const scenario of [
  { position: 'white', player: 'white', outcome: 'Victory', live: true },
  { position: 'black', player: 'black', outcome: 'Victory' },
  { position: 'black', player: 'white', outcome: 'Defeat' },
  { position: 'white', player: 'black', outcome: 'Defeat' },
  { position: 'draw', player: 'white', outcome: 'Draw' },
] as const) {
  test(`${scenario.outcome} from ${scenario.player}'s perspective (${scenario.position})`, async ({ page }, info) => {
    if (info.project.name === 'mobile' && scenario.position === 'draw') {
      await page.setViewportSize({ width: 320, height: 720 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
    }
    const position = positions[scenario.position];
    const chess = new Chess(position.fen);
    const move = chess.move(position.move);
    expect(chess.isGameOver()).toBe(true);
    expect(chess.isCheckmate()).toBe(scenario.position !== 'draw');
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
    const finished: Game = {
      id: 'result-test', initial_fen: position.fen, fen: chess.fen(),
      moves: [{ uci: position.move, san: move.san, fen: chess.fen() }],
      revision: 1, mode: 'training', player_color: scenario.player as Color,
      difficulty: 2, status: scenario.position === 'draw' ? 'stalemate' : 'checkmate', result: position.score,
    };
    let game = 'live' in scenario ? { ...finished, fen: position.fen, moves: [], revision: 0, status: 'playing', result: '*' } : finished;
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body: unknown = [];
      if (path === '/api/profiles') body = [{ id: 'result-profile', name: 'Result test', preferences: {
        ...defaults, player_color: scenario.player, coaching_mode: 'independent',
        play_mode: 'coach_first', auto_computer: false, theme: scenario.outcome === 'Defeat' ? 'dark' : 'light',
      } }];
      else if (path === '/api/games/result-test/moves') {
        expect(route.request().postDataJSON().move).toBe(position.move);
        game = finished;
        body = game;
      } else if (path === '/api/games/result-test') body = game;
      else if (path === '/api/analysis') body = { fen: route.request().postDataJSON().fen, candidates: [], engine_available: false };
      else if (path.endsWith('/conversation')) body = { messages: [] };
      await route.fulfill({ json: body });
    });
    await page.addInitScript(() => localStorage.setItem('chessmate.profile', 'result-profile'));
    await page.goto('/play/result-test');
    const board = page.getByTestId('chessboard');
    const overlay = board.locator('.board-result');
    if ('live' in scenario) {
      await expect(overlay).toHaveCount(0);
      for (const square of ['f7', 'g7']) await board.locator(`[data-square="${square}"]`).click();
    }
    await expect(overlay.getByRole('heading', { name: scenario.outcome, exact: true })).toBeVisible();
    await expect(overlay.getByRole('status')).toContainText(scenario.position === 'draw' ? 'Stalemate' : 'Checkmate');
    await expect(overlay).toContainText(position.score === '1/2-1/2' ? '½ – ½' : position.score.replace('-', ' – '));
    await expect(page).toHaveTitle(/Chessmate/);
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await board.evaluate((element) => element.scrollIntoView({ block: 'center' }));
    await overlay.screenshot({ path: `/tmp/chessmate-result-${info.project.name}-${scenario.position}-${scenario.player}.png`, animations: 'disabled', scale: 'css' });
    const bounds = await board.boundingBox();
    const card = await overlay.locator('.board-result-card').boundingBox();
    expect(Math.abs(card!.x + card!.width / 2 - bounds!.x - bounds!.width / 2)).toBeLessThan(2);
    expect(Math.abs(card!.y + card!.height / 2 - bounds!.y - bounds!.height / 2)).toBeLessThan(2);
    expect(card!.height).toBeLessThan(bounds!.height);
    expect(await overlay.locator('.board-result-close').evaluate((button) => {
      const bounds = button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2));
    })).toBe(true);
    await page.getByRole('button', { name: 'Flip board', exact: true }).click();
    await expect(overlay.getByRole('heading', { name: scenario.outcome, exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Previous move', exact: true }).click();
    await expect(overlay).toHaveCount(0);
    await page.getByRole('button', { name: 'Latest position', exact: true }).click();
    await expect(overlay).toBeVisible();
    await page.getByRole('button', { name: 'Explore position', exact: true }).click();
    await expect(overlay).toHaveCount(0);
    await page.getByRole('button', { name: 'Return to game', exact: true }).click();
    await expect(overlay).toBeVisible();
    await overlay.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(overlay).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}
