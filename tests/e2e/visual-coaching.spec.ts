import {
  test,
  expect,
  type Page,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";

async function setup(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("New profile", { exact: true })
    .fill(`visual_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`);
  const creation = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/profiles",
  );
  await page
    .getByRole("button", { name: "Create profile", exact: true })
    .click();
  const headers = {
    "X-Profile-ID": (await (await creation).json()).id as string,
  };
  await page.request.patch("/api/settings", {
    headers,
    data: {
      auto_computer: false,
      play_mode: "coach_first",
      visual_arrows: "on_request",
    },
  });
  await page.reload();
  await page.getByRole("button", { name: "New game", exact: true }).click();
  await page.getByRole("button", { name: "Start game", exact: true }).click();
  await expect(
    page.getByText("Automatically saved", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/analysis", async (route) => {
    const body = route.request().postDataJSON();
    const root = body.fen.startsWith(
      "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",
    );
    await route.fulfill({
      json: {
        fen: body.fen,
        candidates: root
          ? [
              {
                uci: "e2e4",
                san: "e4",
                cp: 20,
                mate: null,
                pv: ["e4", "e5", "Nf3"],
                pv_uci: ["e2e4", "e7e5", "g1f3"],
              },
            ]
          : [],
      },
    });
  });
  return headers;
}
test.afterEach(async ({ page }) => {
  const profile = await page.evaluate(() =>
    localStorage.getItem("chessmate.profile"),
  );
  if (profile) await page.request.delete(`/api/profiles/${profile}`);
});

test("compare offers three legal practice choices and previews them without changing the game", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const headers = await setup(page);
  await page.unroute("**/api/analysis");
  const saved = (await (await page.request.get("/api/games", { headers })).json())[0];
  for (let attempt = 0; attempt < 2; attempt++) {
    const response = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/analysis" &&
      response.request().postDataJSON()?.candidate_selection === "practice",
    );
    await page.getByRole("button", { name: "Compare 3 moves", exact: true }).click();
    const result = await response;
    expect(result.ok()).toBe(true);
    const analysis = await result.json();
    expect(new Set(analysis.candidates.map((c: { uci: string }) => c.uci)).size).toBe(3);
    await expect(page.locator(".candidate-title")).toHaveCount(3);
    for (const candidate of analysis.candidates) {
      expect(saved.legal_moves).toContain(candidate.uci);
      await expect(page.locator(".candidate-title").getByText(candidate.san, { exact: true })).toHaveCount(1);
    }
  }
  await page.locator(".candidate-title").first().click();
  await page.getByRole("button", { name: "Preview variation", exact: true }).first().click();
  await expect(page.getByRole("region", { name: "Variation playback" })).toBeVisible();
  await page.getByRole("button", { name: "Return to game", exact: true }).click();
  await expect(page.getByRole("region", { name: "Variation playback" })).toHaveCount(0);
  const restored = await (await page.request.get(`/api/games/${saved.id}`, { headers })).json();
  expect(restored.fen).toBe(saved.fen);
  expect(restored.revision).toBe(saved.revision);
  expect(restored.moves).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `/tmp/chessmate-compare-three-${info.project.name}.png`, fullPage: true, animations: "disabled" });
});

test("visual variation can be stepped, reversed, paused and returned without saving moves", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const headers = await setup(page);
  const saved = (
    await (await page.request.get("/api/games", { headers })).json()
  )[0];
  await page
    .getByRole("button", { name: "Compare 3 moves", exact: true })
    .click();
  await page.locator(".candidate-title").click();
  const arrow = page.locator('path[marker-end*="e2-e4"]');
  await expect(arrow).toBeAttached();
  await expect(arrow.locator("..")).toBeVisible();
  const whitePath = await arrow.getAttribute("d");
  const whiteCoordinates = whitePath!.match(/[\d.]+/g)!.map(Number);
  expect(whiteCoordinates[1]).toBeGreaterThan(whiteCoordinates[3]);
  await page.screenshot({
    path: `/tmp/chessmate-arrow-white-${info.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Flip board", exact: true }).click();
  await expect(arrow).toBeAttached();
  await expect(arrow.locator("..")).toBeVisible();
  const blackPath = await arrow.getAttribute("d");
  expect(blackPath).not.toBe(whitePath);
  const blackCoordinates = blackPath!.match(/[\d.]+/g)!.map(Number);
  expect(blackCoordinates[1]).toBeLessThan(blackCoordinates[3]);
  await page.screenshot({
    path: `/tmp/chessmate-arrow-black-${info.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Preview variation", exact: true })
    .click();
  const player = page.getByRole("region", { name: "Variation playback" });
  await expect(player).toContainText("1 / 3");
  await page
    .getByRole("button", { name: "Next variation move", exact: true })
    .click();
  await expect(player).toContainText("2 / 3");
  await page
    .getByRole("button", { name: "Previous variation move", exact: true })
    .click();
  await expect(player).toContainText("1 / 3");
  await page
    .getByRole("button", { name: "Variation start", exact: true })
    .click();
  await expect(player).toContainText("0 / 3");
  await page.getByLabel("Playback speed", { exact: true }).selectOption("1800");
  await page
    .getByRole("button", { name: "Play variation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Pause variation", exact: true })
    .click();
  await expect(player).toContainText("0 / 3");
  await page
    .getByRole("button", { name: "Variation end", exact: true })
    .click();
  await expect(player).toContainText("3 / 3");
  await page.screenshot({
    path: `/tmp/chessmate-visual-${info.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Return to game", exact: true })
    .click();
  await expect(player).not.toBeVisible();
  const restored = await (
    await page.request.get(`/api/games/${saved.id}`, { headers })
  ).json();
  expect(restored.fen).toBe(saved.fen);
  expect(restored.revision).toBe(saved.revision);
  expect(restored.moves).toEqual([]);
  expect(errors).toEqual([]);
});

test("hints highlight the source then draw a move arrow without leaking extra visual metadata and calculation rejects illegal lines", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/hint", (route) =>
    route.fulfill({
      json: {
        text: "Check the center.",
        highlight_square: route.request().postDataJSON().level === 1 ? "e2" : undefined,
        highlight_move: "e2e4",
        insights: [
          {
            id: "unsafe-early",
            text: "Play e4",
            fen: route.request().postDataJSON().fen,
            squares: ["e4"],
            arrows: [{ from: "e2", to: "e4" }],
          },
        ],
        variations: [],
      },
    }),
  );
  await page
    .getByRole("button", { name: "Give me a hint", exact: true })
    .click();
  await expect(page.getByTestId("position-hint")).toContainText(
    "Check the center.",
  );
  const firstHint = page.getByTestId("position-hint");
  await expect(firstHint).not.toContainText("Play e4");
  await expect(firstHint.getByRole("button", { name: "e4", exact: true })).toHaveCount(0);
  await expect(firstHint.getByRole("button", { name: "Preview variation", exact: true })).toHaveCount(0);
  await expect(page.locator('path[marker-end*="e2-e4"]')).toHaveCount(0);
  const source = page.locator('[data-square="e2"] .board-square');
  const destination = page.locator('[data-square="e4"] .board-square');
  await expect(source).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
  await expect(destination).toHaveCSS('box-shadow', 'none');
  await page.getByRole('button', { name: /Next hint/ }).click();
  await expect(destination).toHaveCSS('box-shadow', 'none');
  await expect(source).toHaveCSS('box-shadow', 'none');
  await expect(page.locator('path[marker-end*="e2-e4"]')).toHaveCount(1);
  await page
    .getByRole("button", { name: "Calculate before moving", exact: true })
    .click();
  await page
    .getByLabel("Your predicted line (SAN or UCI)", { exact: true })
    .fill("e2e5");
  await page
    .getByRole("button", { name: "Check calculation", exact: true })
    .click();
  await expect(
    page.getByText(
      "That line contains an illegal move. Check whose turn it is and try again.",
    ),
  ).toBeVisible();
  await page.route("**/api/calculation", (route) =>
    route.fulfill({
      json: {
        fen: route.request().postDataJSON().fen,
        text: "Your line is legal. Review the opponent’s reply.",
        first_inaccuracy_ply: null,
        steps: [],
      },
    }),
  );
  await page
    .getByLabel("Your predicted line (SAN or UCI)", { exact: true })
    .fill("e4 e5 Nf3");
  await page
    .getByRole("button", { name: "Check calculation", exact: true })
    .click();
  await expect(page.locator(".calculation-practice")).toContainText(
    "Your line is legal.",
  );
});

test('hints highlight a checked king and clear after moving', async ({ page }, info) => {
  const headers = await setup(page);
  await page.request.patch('/api/settings', { headers, data: { highlight_pieces: false, explanation_mode: 'text' } });
  const created = await page.request.post('/api/games', { headers, data: {
    fen: '6k1/8/8/8/8/8/4r3/4K3 w - - 0 1', player_color: 'white',
  } });
  expect(created.status()).toBe(201);
  const game = await created.json();
  await page.goto(`/play/${game.id}`);
  await page.route('**/api/hint', (route) => route.fulfill({ json: {
    fen: game.fen,
    text: route.request().postDataJSON().level === 1 ? 'Focus on your king.' : 'Move the king to e2.',
    highlight_square: route.request().postDataJSON().level === 1 ? 'e1' : undefined,
    highlight_move: 'e1e2',
  } }));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text());
  });
  await expect(page).toHaveTitle(/Chessmate/);
  await expect(page).toHaveURL(`/play/${game.id}`);
  await expect(page.getByTestId('chessboard')).toBeVisible();
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.getByRole('button', { name: 'Give me a hint', exact: true }).click();
  await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
  await page.getByTestId('chessboard').screenshot({ path: `/tmp/chessmate-hint-source-${info.project.name}.png` });
  await page.getByRole('button', { name: /Next hint/ }).click();
  await expect(page.locator('path[marker-end*="e1-e2"]')).toHaveCount(1);
  await expect(page.locator('[data-square="e1"] .board-square')).toHaveCSS('box-shadow', 'none');
  await page.getByTestId('chessboard').screenshot({ path: `/tmp/chessmate-hint-destination-${info.project.name}.png` });
  await page.locator('[data-square="e1"]').click();
  await page.locator('[data-square="e2"]').click();
  await expect(page.getByTestId('position-hint')).toHaveCount(0);
  await expect(page.locator('path[marker-end*="e1-e2"]')).toHaveCount(0);
  await expect(page.locator('[data-square="e2"] .board-square')).toHaveCSS('box-shadow', 'none');
  expect(errors).toEqual([]);
});

test("real calculation identifies a failed tactic and full-game analysis assesses imported moves", async ({
  page,
}) => {
  const headers = await setup(page);
  const fen = "6k1/5ppp/8/8/8/q7/1P3PPP/4R1K1 b - - 0 1";
  const position = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", player_color: "black", fen },
    })
  ).json();
  await page.goto(`/analyze/${position.id}`);
  await page.getByRole("tab", { name: "Chat", exact: true }).click();
  await page
    .getByRole("button", { name: "Calculate before moving", exact: true })
    .click();
  await page
    .getByLabel("Your predicted line (SAN or UCI)", { exact: true })
    .fill("Qxb2 Re8#");
  await page
    .getByLabel("Your assessment of the final position", { exact: true })
    .selectOption("winning");
  await page
    .getByRole("button", { name: "Check calculation", exact: true })
    .click();
  await expect(page.locator(".calculation-practice")).toContainText(
    "The first weaker prediction is ply 1",
  );
  await expect(page.locator(".calculation-practice")).toContainText("Losing");
  await page
    .locator(".calculation-practice")
    .getByRole("button", { name: "Show on board", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Variation end", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Variation playback" }),
  ).toContainText("Re8#");
  const saved = await (
    await page.request.get(`/api/games/${position.id}`, { headers })
  ).json();
  expect(saved.fen).toBe(fen);
  expect(saved.moves).toEqual([]);
  const imported = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", pgn: "1. e4 e5 2. Nf3 Nc6 *" },
    })
  ).json();
  await page.goto(`/analyze/${imported.id}`);
  await page
    .getByRole("button", { name: "Analyze every move", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Analyze every move", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".quality-summary")).toContainText("4");
  const analyzed = await (
    await page.request.get(`/api/games/${imported.id}`, { headers })
  ).json();
  expect(
    analyzed.moves.every((move: { feedback?: unknown }) => !!move.feedback),
  ).toBe(true);
  expect(analyzed.moves.map((move: { uci: string }) => move.uci)).toEqual(
    imported.moves.map((move: { uci: string }) => move.uci),
  );
});

test("ambiguous coaching references let the player choose the intended source piece", async ({
  page,
}) => {
  const headers = await setup(page);
  const fen = "4k3/p7/8/8/8/2N3N1/8/4K3 w - - 0 1";
  const position = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", fen },
    })
  ).json();
  const questions: string[] = [];
  await page.route("**/api/coach", async (route) => {
    questions.push(route.request().postDataJSON().question);
    const payload =
      questions.length === 1
        ? {
            text: "Which knight do you mean?",
            ambiguous_moves: [
              {
                reference: "knight to e4",
                choices: [
                  { uci: "c3e4", san: "Nce4", from: "c3", to: "e4" },
                  { uci: "g3e4", san: "Nge4", from: "g3", to: "e4" },
                ],
              },
            ],
          }
        : {
            text: "Now we can examine the knight from c3.",
            ambiguous_moves: [],
          };
    await route.fulfill({
      contentType: "text/event-stream",
      body: `event: done\ndata: ${JSON.stringify(payload)}\n\n`,
    });
  });
  await page.goto(`/analyze/${position.id}`);
  await page.getByRole("tab", { name: "Chat", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Ask about this position…", exact: true })
    .fill("What if I move my knight to e4?");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Which knight do you mean?", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Nce4 · c3 → e4", exact: true })
    .click();
  await expect(
    page.getByText("Now we can examine the knight from c3.", { exact: true }),
  ).toBeVisible();
  expect(questions).toEqual([
    "What if I move my knight to e4?",
    "What if I play c3e4?",
  ]);
  const saved = await (
    await page.request.get(`/api/games/${position.id}`, { headers })
  ).json();
  expect(saved.moves).toEqual([]);
});

test("retrying a verified game mistake opens a tracked private exercise and preserves the game", async ({
  page,
}) => {
  const headers = await setup(page);
  const fen = "6k1/5ppp/8/8/8/q7/1P3PPP/4R1K1 b - - 0 1";
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", player_color: "black", fen },
    })
  ).json();
  const saved = await (
    await page.request.post(`/api/games/${game.id}/moves`, {
      headers,
      data: { move: "a3b2", revision: game.revision },
    })
  ).json();
  expect(saved.moves[0].feedback.classification).toBe("Blunder");
  await page.goto(`/analyze/${game.id}`);
  await page.locator(".review-move").click();
  await page.getByLabel("Your intended move", { exact: true }).fill("Consider the forcing reply before capturing the pawn.");
  await page.getByRole("button", { name: "Reveal engine feedback", exact: true }).click();
  await expect(page.locator(".review-decision")).toContainText(
    "Analysis confidence:",
  );
  await page
    .getByRole("button", { name: "Retry this position", exact: true })
    .click();
  await expect(page).toHaveURL(/\/learn\/[^/]+\/exercises\/game-/);
  await expect(
    page.getByRole("link", { name: "Return to your game", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("The solution", { exact: true })).toHaveCount(0);
  const exerciseId = decodeURIComponent(
    new URL(page.url()).pathname.split("/").at(-1)!,
  );
  const response = await page.request.post(
    `/api/exercises/${exerciseId}/attempt`,
    { headers, data: { moves: ["a3b2"] } },
  );
  expect(response.ok()).toBe(true);
  expect((await response.json()).correct).toBe(false);
  const progress = await (
    await page.request.get("/api/progress", { headers })
  ).json();
  expect(progress.attempts).toBeGreaterThanOrEqual(1);
  await page
    .getByRole("link", { name: "Return to your game", exact: true })
    .click();
  await expect(page).toHaveURL(`/analyze/${game.id}`);
  const restored = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(restored.fen).toBe(saved.fen);
  expect(restored.revision).toBe(saved.revision);
  expect(restored.moves.map((move: { uci: string }) => move.uci)).toEqual([
    "a3b2",
  ]);
});
