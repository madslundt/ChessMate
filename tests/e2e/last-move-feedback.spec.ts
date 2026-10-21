import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';
import { defaults, type Game, type Feedback } from '../../src/frontend/src/types';

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

test('bad-move labels highlight threats and the better move on their own positions without changing the game', async ({ page }, info) => {
  const chess = new Chess();
  const initialFen = chess.fen();
  const moves = ['f3', 'e5', 'g4', 'Nc6'].map((san) => {
    const before_fen = chess.fen(), move = chess.move(san);
    return { uci: move.lan, san, before_fen, fen: chess.fen(), feedback: { classification: 'Good', text: 'Development.' } as Feedback };
  });
  const mate = new Chess(moves[2].fen);
  mate.move('Qh4#');
  moves[2].feedback = {
    classification: 'Blunder', consequence: 'Moving the g-pawn leaves your king exposed to Qh4 checkmate.',
    threats: [{ id: 'g4-mate', label: 'Qh4# · checkmate', text: 'Qh4 is checkmate in this continuation.',
      fen: mate.fen(), claim_type: 'engine_threat', squares: ['h4', 'e1'], arrows: [{ from: 'h4', to: 'e1', color: 'red' }] }],
    improvement: { uci: 'd2d4', san: 'd4', fen: moves[2].before_fen },
  };
  const game: Game = { id: 'feedback-highlights', initial_fen: initialFen, fen: chess.fen(), moves, revision: 4,
    mode: 'training', player_color: 'white', difficulty: 2, status: 'playing', result: '*' };
  const saved = JSON.stringify(game), mutations: string[] = [], errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET' && pathname.startsWith('/api/games')) mutations.push(pathname);
    let body: unknown = [];
    if (pathname === '/api/profiles') body = [{ id: 'highlight-profile', name: 'Highlight test', preferences: {
      ...defaults, coaching_mode: 'independent', play_mode: 'coach_first', auto_computer: false,
      visual_arrows: 'on_request', highlight_threats: false, highlight_pieces: false, animate_variations: false, explanation_mode: 'text',
    } }];
    else if (pathname === '/api/games/feedback-highlights') body = game;
    else if (pathname.endsWith('/conversation')) body = { messages: [
      { id: 'reference-user', role: 'user', fen: initialFen, content: 'What about g1f3 and c6?' },
      { id: 'reference-coach', role: 'assistant', fen: initialFen, content: 'Try 1.e4 e5 2.Nf3 Nc6. Watch the king on e1.' },
    ] };
    else if (pathname.endsWith('/review')) body = { summary: '', topics: [] };
    else if (pathname === '/api/settings/speech') body = { stt_mode: 'browser', tts_mode: 'browser' };
    else if (pathname === '/api/analysis') body = { fen: route.request().postDataJSON().fen, candidates: [] };
    await route.fulfill({ json: body });
  });
  await page.addInitScript(() => localStorage.setItem('chessmate.profile', 'highlight-profile'));
  await page.goto('/play/feedback-highlights');
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page).toHaveURL('/play/feedback-highlights');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  const white = page.getByRole('region', { name: 'Last move feedback', exact: true }).getByRole('article', { name: 'White', exact: true });
  const threat = white.getByRole('button', { name: 'Qh4# · checkmate', exact: true });
  const better = white.getByRole('button', { name: 'd4', exact: true });
  await expect(white).toContainText('A better move was d4.');
  await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  if (info.project.name === 'desktop') {
    await threat.hover();
    await expect(page.locator('[data-square="h4"] [data-piece="bQ"]')).toHaveCount(1);
    await expect(page.locator('path[marker-end*="h4-e1"]')).toBeAttached();
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(threat).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
    await expect(page.locator('.board-explanation')).toHaveCount(0);
  }
  await threat.click();
  await expect(threat).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-square="h4"] [data-piece="bQ"]')).toHaveCount(1);
  await expect(page.locator('[data-square="b8"] [data-piece="bN"]')).toHaveCount(1);
  await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
  await expect(page.locator('path[marker-end*="h4-e1"]')).toBeAttached();
  await expect(page.locator('.position-score')).toContainText('Black wins');
  await expect(page.locator('.board-explanation')).toContainText('Showing the position for this explanation');
  await page.screenshot({ path: `/tmp/chessmate-threat-label-${info.project.name}.png`, fullPage: true });
  await threat.click();
  await expect(threat).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  await better.click();
  await expect(better).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(0);
  await expect(page.locator('path[marker-end*="d2-d4"]')).toBeAttached();
  if (info.project.name === 'desktop') {
    // A temporary hover can show a different position without replacing a clicked highlight.
    await threat.hover();
    await expect(page.locator('[data-square="h4"] [data-piece="bQ"]')).toHaveCount(1);
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(better).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('path[marker-end*="d2-d4"]')).toBeAttached();
    await expect(page.locator('[data-square="g2"] [data-piece="wP"]')).toHaveCount(1);
  }
  await page.getByRole('button', { name: 'Flip board', exact: true }).click();
  await expect(page.locator('path[marker-end*="d2-d4"]')).toBeAttached();
  await page.screenshot({ path: `/tmp/chessmate-improvement-label-${info.project.name}.png`, fullPage: true });
  await page.getByRole('button', { name: 'Clear board explanation', exact: true }).click();
  await expect(better).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('[data-square="g4"] [data-piece="wP"]')).toHaveCount(1);
  await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  // Inline feedback, square names, and historical chat references work in text-only mode,
  // even when automatic highlights are disabled. Explicit clicks never play moves.
  const inlineThreat = white.getByRole('button', { name: 'Qh4', exact: true });
  if (info.project.name === 'desktop') {
    await inlineThreat.hover();
    await expect(page.locator('path[marker-end*="d8-h4"]')).toBeAttached();
    await page.screenshot({ path: '/tmp/chessmate-hover-feedback-desktop.png', fullPage: true });
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(page.locator('path[marker-end*="d8-h4"]')).toHaveCount(0);
    await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  }
  await inlineThreat.click();
  await expect(inlineThreat).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('path[marker-end*="d8-h4"]')).toBeAttached();
  await page.getByRole('button', { name: 'Clear board explanation', exact: true }).click();
  const played = white.locator('.last-move-feedback-san').getByRole('button', { name: 'g4', exact: true });
  await played.click();
  await expect(page.locator('path[marker-end*="g2-g4"]')).toBeAttached();
  await played.click();
  const user = page.locator('.chat-message.user');
  const assistant = page.locator('.chat-message.assistant');
  if (info.project.name === 'desktop') {
    await user.getByRole('button', { name: 'g1f3', exact: true }).hover();
    await expect(page.locator('path[marker-end*="g1-f3"]')).toBeAttached();
    await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(0);
    await assistant.getByRole('button', { name: 'e1', exact: true }).hover();
    await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
    await expect(page.locator('path[marker-end*="g1-f3"]')).toHaveCount(0);
    await page.screenshot({ path: '/tmp/chessmate-hover-square-desktop.png', fullPage: true });
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(page.locator('.board-explanation')).toHaveCount(0);
    await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  }
  if (info.project.name === 'desktop') {
    const userMove = user.getByRole('button', { name: 'g1f3', exact: true });
    const chatSquare = assistant.getByRole('button', { name: 'e1', exact: true });
    // Mouse and keyboard previews restore one another, whichever was activated last.
    await userMove.focus();
    await chatSquare.hover();
    await expect(page.locator('path[marker-end*="g1-f3"]')).toHaveCount(0);
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(page.locator('path[marker-end*="g1-f3"]')).toBeAttached();
    await userMove.blur();
    await expect(page.locator('.board-explanation')).toHaveCount(0);
    await userMove.hover();
    await chatSquare.focus();
    await page.getByRole('heading', { name: 'Play', exact: true }).hover();
    await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
    await chatSquare.blur();
    await expect(page.locator('.board-explanation')).toHaveCount(0);
  }
  await user.getByRole('button', { name: 'g1f3', exact: true }).click();
  await expect(page.locator('path[marker-end*="g1-f3"]')).toBeAttached();
  await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(0);
  const square = assistant.getByRole('button', { name: 'e1', exact: true });
  await square.focus();
  await page.keyboard.press('Enter');
  await expect(square).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
  await assistant.getByRole('button', { name: 'Nc6', exact: true }).click();
  await expect(page.locator('path[marker-end*="b8-c6"]')).toBeAttached();
  await expect(page.locator('[data-square="f3"] [data-piece="wN"]')).toHaveCount(1);
  await expect(page.locator('[data-square="e5"] [data-piece="bP"]')).toHaveCount(1);
  await page.screenshot({ path: `/tmp/chessmate-inline-references-${info.project.name}.png`, fullPage: true });
  await page.getByRole('button', { name: 'Clear board explanation', exact: true }).click();
  await expect(page.locator('[data-square="c6"] [data-piece="bN"]')).toHaveCount(1);
  // The same controls work in the coaching timeline and the game review.
  const coach = page.locator('.move-feedback-entry.white.blunder');
  await expect(coach.locator('.feedback-highlights')).toHaveCSS('display', 'block');
  await coach.getByRole('button', { name: 'd4', exact: true }).click();
  await expect(coach.getByRole('button', { name: 'd4', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Clear board explanation', exact: true }).click();
  await page.goto('/analyze/feedback-highlights');
  await page.locator('.review-move').filter({ hasText: 'g4' }).click();
  await page.getByRole('button', { name: 'Reveal engine feedback', exact: true }).click();
  const review = page.getByRole('region', { name: 'Why this was bad', exact: true });
  await review.getByRole('button', { name: 'Qh4# · checkmate', exact: true }).click();
  await expect(page.locator('[data-square="h4"] [data-piece="bQ"]')).toHaveCount(1);
  await review.getByRole('button', { name: 'd4', exact: true }).click();
  await expect(page.locator('path[marker-end*="d2-d4"]')).toBeAttached();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(mutations).toEqual([]);
  expect(JSON.stringify(game)).toBe(saved);
  expect(errors).toEqual([]);
});
