import { test, expect, type Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';
import { defaults, type Game } from '../../src/frontend/src/types';

async function board(
  page: Page,
  initialFen = new Chess().fen(),
  playerColor: 'white' | 'black' = 'white',
  showLegalMoves = true,
) {
  let game: Game = {
    id: 'movement-test',
    initial_fen: initialFen,
    fen: initialFen,
    moves: [],
    revision: 0,
    mode: 'training',
    player_color: playerColor,
    difficulty: 2,
    status: 'playing',
    result: '*',
  };
  let respond!: (outcome: 'success' | 'failure' | 'conflict' | 'offline') => void;
  const response = new Promise<'success' | 'failure' | 'conflict' | 'offline'>((resolve) => (respond = resolve));
  const requests: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path !== '/api/profiles') expect(route.request().headers()['x-profile-id']).toBe('movement-profile');
    let body: unknown = [];
    if (path === '/api/profiles') {
      body = [
        {
          id: 'movement-profile',
          name: 'Movement test',
          preferences: {
            ...defaults,
            coaching_mode: 'independent',
            auto_computer: false,
            show_legal_moves: showLegalMoves,
          },
        },
      ];
    } else if (path === '/api/games/movement-test/moves') {
      const { move, revision } = route.request().postDataJSON();
      requests.push(move);
      expect(revision).toBe(game.revision);
      const outcome = await response;
      if (outcome === 'offline') return route.abort('failed');
      if (outcome !== 'success') {
        return route.fulfill({
          status: outcome === 'conflict' ? 409 : 500,
          json: { detail: 'Move was not saved' },
        });
      }
      const chess = new Chess(game.fen);
      const played = chess.move(move);
      game = {
        ...game,
        fen: chess.fen(),
        revision: game.revision + 1,
        moves: [...game.moves, { uci: move, san: played.san, fen: chess.fen(), actor: 'player' }],
      };
      body = game;
    } else if (path === '/api/games/movement-test') body = game;
    else if (path.endsWith('/conversation')) body = { messages: [] };
    await route.fulfill({ json: body });
  });
  await page.addInitScript(() => {
    localStorage.setItem('chessmate.profile', 'movement-profile');
  });
  await page.goto('/play/movement-test');
  await expect(page.getByTestId('chessboard')).toHaveAttribute(
    'aria-label',
    `${new Chess(initialFen).turn() === 'w' ? 'White' : 'Black'} to move`,
  );
  await expect(page.getByText('Automatically saved', { exact: true })).toBeVisible();
  return { respond, requests, errors };
}

function piece(page: Page, square: string, type: string) {
  return page.locator(`[data-square="${square}"] [data-piece="${type}"]`);
}

async function move(page: Page, from: string, to: string, drag = false) {
  if (drag) {
    const source = (await page.locator(`[data-square="${from}"]`).boundingBox())!;
    const target = (await page.locator(`[data-square="${to}"]`).boundingBox())!;
    await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 12 });
    await page.mouse.up();
  } else {
    const touch = await page.evaluate(() => navigator.maxTouchPoints > 0);
    for (const square of [from, to]) {
      const target = page.locator(`[data-square="${square}"]`);
      if (touch) await target.tap();
      else await target.click();
    }
  }
}

test('legal destinations glow immediately while holding and dragging a piece', async ({ page }, info) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') consoleErrors.push(message.text());
  });
  const state = await board(page);
  expect(new URL(page.url()).pathname).toBe('/play/movement-test');
  await expect(page).toHaveTitle('Chessmate');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  const source = (await piece(page, 'e2', 'wP').boundingBox())!;
  const target = (await page.locator('[data-square="e4"]').boundingBox())!;
  const glow = page.locator('.board-square--legal-glow');
  const touch = info.project.name !== 'desktop';
  const session = touch ? await page.context().newCDPSession(page) : null;
  const point = {
    x: source.x + source.width / 2,
    y: source.y + source.height / 2,
  };
  if (session)
    await session.send('Input.dispatchTouchEvent', {
      type: 'touchStart',
      touchPoints: [point],
    });
  else {
    await page.mouse.move(point.x, point.y);
    await page.mouse.down();
  }
  await expect(glow).toHaveCount(2);
  for (const square of ['e3', 'e4']) {
    await expect(page.locator(`[data-square="${square}"] .board-square`)).toHaveClass(/legal-glow/);
  }
  await expect(glow.first()).toHaveCSS('box-shadow', /inset/);
  expect(state.requests).toEqual([]);
  try {
    if (session) {
      for (let step = 1; step <= 12; step++) {
        await session.send('Input.dispatchTouchEvent', {
          type: 'touchMove',
          touchPoints: [
            {
              x: point.x + ((target.x + target.width / 2 - point.x) * step) / 12,
              y: point.y + ((target.y + target.height / 2 - point.y) * step) / 12,
            },
          ],
        });
      }
    } else {
      await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 12 });
    }
    await expect(glow).toHaveCount(2);
    await page.getByTestId('chessboard').screenshot({
      path: `/tmp/chessmate-held-moves-${info.project.name}.png`,
    });
    if (session)
      await session.send('Input.dispatchTouchEvent', {
        type: 'touchEnd',
        touchPoints: [],
      });
    else await page.mouse.up();
    await expect(glow).toHaveCount(0);
    await expect(piece(page, 'e4', 'wP')).toHaveCount(1);
    await expect.poll(() => state.requests).toEqual(['e2e4']);
  } finally {
    state.respond('success');
  }
  expect(state.errors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('holding only lights legal moves, including captures, and clears outside the board', async ({ page }) => {
  const state = await board(page, '7k/8/8/3pP3/8/8/8/4R2K w - d6 0 1');
  const source = (await piece(page, 'e5', 'wP').boundingBox())!;
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await expect(page.locator('.board-square--legal-glow')).toHaveCount(2);
  await expect(page.locator('[data-square="d6"] .board-square')).toHaveClass(/legal-glow/);
  await page.mouse.move(0, 0, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator('.board-square--legal-glow')).toHaveCount(0);
  expect(state.requests).toEqual([]);
  expect(state.errors).toEqual([]);
});

test('holding respects hidden legal moves', async ({ page }) => {
  const state = await board(page, new Chess().fen(), 'white', false);
  const source = (await piece(page, 'e2', 'wP').boundingBox())!;
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await expect(page.locator('.board-square--legal-glow')).toHaveCount(0);
  await page.mouse.up();
  expect(state.requests).toEqual([]);
  expect(state.errors).toEqual([]);
});

for (const drag of [false, true]) {
  test(`player ${drag ? 'drag' : 'click'} move lands before the save response`, async ({ page }) => {
    const state = await board(page);
    await expect(piece(page, 'e2', 'wP')).toHaveCount(1);
    try {
      await move(page, 'e2', 'e4', drag);
      // The response remains held until after these assertions: network/engine latency must not delay the piece.
      await expect(piece(page, 'e4', 'wP')).toHaveCount(1, { timeout: 350 });
      await expect(piece(page, 'e2', 'wP')).toHaveCount(0);
      await expect.poll(() => state.requests).toEqual(['e2e4']);
      await move(page, 'd2', 'd4', drag);
      expect(state.requests).toEqual(['e2e4']);
      await expect(piece(page, 'd2', 'wP')).toHaveCount(1);
    } finally {
      state.respond('success');
    }
    await page.getByRole('button', { name: /^Moves/ }).click();
    await expect(page.locator('.move-table')).toContainText('e4');
    await expect(piece(page, 'e4', 'wP')).toHaveCount(1);
    expect(state.errors).toEqual([]);
  });
}

for (const outcome of ['failure', 'conflict', 'offline'] as const) {
  test(`player move rolls back after ${outcome}`, async ({ page }) => {
    const state = await board(page);
    try {
      await move(page, 'e2', 'e4');
      await expect(piece(page, 'e4', 'wP')).toHaveCount(1, { timeout: 350 });
    } finally {
      state.respond(outcome);
    }
    await expect(piece(page, 'e2', 'wP')).toHaveCount(1);
    await expect(piece(page, 'e4', 'wP')).toHaveCount(0);
    await expect(page.locator('.error-notice')).toBeVisible();
    await expect(page.getByRole('button', { name: 'e2 White p', exact: true })).toHaveAttribute('tabindex', '0');
    expect(state.errors).toEqual([]);
  });
}

for (const scenario of [
  {
    name: 'black move on a flipped board',
    fen: 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
    from: 'e7',
    to: 'e5',
    type: 'bP',
    color: 'black' as const,
  },
  {
    name: 'castling',
    fen: 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
    from: 'e1',
    to: 'g1',
    type: 'wK',
  },
  {
    name: 'en passant',
    fen: '7k/8/8/3pP3/8/8/8/7K w - d6 0 1',
    from: 'e5',
    to: 'd6',
    type: 'wP',
  },
  {
    name: 'underpromotion',
    fen: '7k/P7/8/8/8/8/8/7K w - - 0 1',
    from: 'a7',
    to: 'a8',
    type: 'wN',
  },
]) {
  test(`player ${scenario.name} appears while saving`, async ({ page }) => {
    const state = await board(page, scenario.fen, scenario.color);
    try {
      await move(page, scenario.from, scenario.to);
      if (scenario.name === 'underpromotion') {
        const dialog = page.getByRole('dialog', { name: 'Choose a promotion' });
        await expect(dialog).toBeVisible();
        expect(state.requests).toEqual([]);
        await dialog.getByRole('button', { name: 'n', exact: true }).click();
      }
      await expect(piece(page, scenario.to, scenario.type)).toHaveCount(1, {
        timeout: 350,
      });
      if (scenario.name === 'castling') await expect(piece(page, 'f1', 'wR')).toHaveCount(1);
      if (scenario.name === 'en passant') await expect(piece(page, 'd5', 'bP')).toHaveCount(0);
    } finally {
      state.respond('success');
    }
    await expect(page.locator('.board-toolbar .loading')).toHaveCount(0);
    await expect(piece(page, scenario.to, scenario.type)).toHaveCount(1);
    expect(state.errors).toEqual([]);
  });
}

test('illegal player move keeps the saved position', async ({ page }) => {
  const state = await board(page);
  await move(page, 'e2', 'e5');
  await expect(piece(page, 'e2', 'wP')).toHaveCount(1);
  await expect(piece(page, 'e5', 'wP')).toHaveCount(0);
  expect(state.requests).toEqual([]);
  expect(state.errors).toEqual([]);
});
