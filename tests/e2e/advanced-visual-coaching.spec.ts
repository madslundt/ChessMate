import {
  test,
  expect,
  type Page,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";

async function setup(page: Page, overrides: Record<string, unknown> = {}) {
  const profile = await (
    await page.request.post("/api/profiles", {
      data: {
        name: `advanced_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      },
    })
  ).json();
  const headers = { "X-Profile-ID": profile.id };
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "training" },
    })
  ).json();
  const preferences = {
    ...profile.preferences,
    play_mode: "coach_first",
    auto_computer: false,
    visual_arrows: "on_request",
    animate_variations: false,
    return_after_playback: false,
    ...overrides,
  };
  await page.addInitScript(
    (id) => localStorage.setItem("chessmate.profile", id),
    profile.id,
  );
  await page.route("**/api/profiles", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({ json: [{ ...profile, preferences }] });
  });
  const candidates = [
    {
      uci: "e2e4",
      san: "e4",
      cp: 25,
      mate: null,
      pv: ["e4", "e5", "Nf3"],
      pv_uci: ["e2e4", "e7e5", "g1f3"],
    },
    {
      uci: "d2d4",
      san: "d4",
      cp: 20,
      mate: null,
      pv: ["d4", "d5", "c4"],
      pv_uci: ["d2d4", "d7d5", "c2c4"],
    },
    {
      uci: "g1f3",
      san: "Nf3",
      cp: 15,
      mate: null,
      pv: ["Nf3", "d5", "d4"],
      pv_uci: ["g1f3", "d7d5", "d2d4"],
    },
  ];
  await page.route("**/api/analysis", (route) =>
    route.fulfill({
      json: {
        fen: route.request().postDataJSON().fen,
        candidates,
        confidence: "search_estimate",
      },
    }),
  );
  await page.goto(`/play/${game.id}`);
  await expect(page.getByTestId("chessboard")).toBeVisible();
  return { headers, game, preferences, candidates };
}
async function move(
  page: Page,
  from: string,
  to: string,
  scope = '[data-testid="chessboard"]',
) {
  for (const square of [from, to])
    await page.locator(`${scope} [data-square="${square}"]`).click();
}
test.afterEach(async ({ page }) => {
  const profile = await page.evaluate(() =>
    localStorage.getItem("chessmate.profile"),
  );
  if (profile) await page.request.delete(`/api/profiles/${profile}`);
});

test("predictions can be built and branched on the board, then only the chosen candidate is committed", async ({
  page,
}, info) => {
  const { game, headers } = await setup(page);
  await page.route("**/api/calculation", (route) =>
    route.fulfill({
      json: {
        fen: game.fen,
        text: "The line is legal; compare the reply.",
        first_inaccuracy_ply: null,
        steps: [],
      },
    }),
  );
  await page
    .getByRole("button", { name: "Calculate before moving", exact: true })
    .click();
  await move(page, "e2", "e4", ".calculation-board");
  await expect(page.locator(".calculation-board")).toContainText(
    "Predict the opponent’s reply",
  );
  await move(page, "e7", "e5", ".calculation-board");
  await move(page, "g1", "f3", ".calculation-board");
  await page
    .getByRole("button", { name: "Keep this branch", exact: true })
    .click();
  await page
    .locator(".calculation-board")
    .getByRole("button", { name: "Variation start", exact: true })
    .click();
  await move(page, "d2", "d4", ".calculation-board");
  await page
    .getByRole("button", { name: "Keep this branch", exact: true })
    .click();
  await expect(
    page
      .getByRole("group", { name: "Your calculation branches" })
      .getByRole("button"),
  ).toHaveCount(2);
  await page
    .getByRole("button", { name: "Branch 1 · e4 e5 Nf3", exact: true })
    .click();
  await expect(
    page.getByLabel("Your predicted line (SAN or UCI)", { exact: true }),
  ).toHaveValue("e2e4 e7e5 g1f3");
  await page
    .getByRole("button", { name: "Check calculation", exact: true })
    .click();
  await expect(
    page.getByText("The line is legal; compare the reply.", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: `/tmp/chessmate-calculation-board-${info.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Play my calculated first move", exact: true })
    .click();
  await expect(page.getByTestId("move-feedback")).toBeVisible();
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.moves.map((entry: { uci: string }) => entry.uci)).toEqual([
    "e2e4",
  ]);
  expect(saved.revision).toBe(game.revision + 1);
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PGN", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^chessmate-.*\.pgn$/);
  expect(await download.failure()).toBeNull();
});

test("candidate boards compare the resulting positions after the same number of plies", async ({
  page,
}, info) => {
  const { game, headers } = await setup(page);
  await page
    .getByRole("button", { name: "Compare 3 moves", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Compare resulting positions", exact: true })
    .click();
  const boards = page.locator(".comparison-boards article");
  await expect(boards).toHaveCount(3);
  await page
    .getByRole("slider", { name: "Compare after half-moves", exact: true })
    .press("ArrowRight");
  await expect(
    boards.nth(0).locator('[data-square="e5"] [data-piece="bP"]'),
  ).toHaveCount(1);
  await expect(
    boards.nth(1).locator('[data-square="d5"] [data-piece="bP"]'),
  ).toHaveCount(1);
  await page.screenshot({
    path: `/tmp/chessmate-result-comparison-${info.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.fen).toBe(game.fen);
  expect(saved.revision).toBe(game.revision);
});

test("deep analysis can be cancelled and a later job can complete", async ({
  page,
}) => {
  const { game, candidates } = await setup(page);
  let cancelled = 0;
  let complete = false;
  await page.route("**/api/analysis/jobs", (route) =>
    route.fulfill({
      status: 202,
      json: { id: "test-job", fen: game.fen, status: "queued" },
    }),
  );
  await page.route("**/api/analysis/jobs/test-job", (route) => {
    if (route.request().method() === "DELETE") {
      cancelled++;
      return route.fulfill({
        json: { id: "test-job", fen: game.fen, status: "cancelled" },
      });
    }
    return route.fulfill({
      json: {
        id: "test-job",
        fen: game.fen,
        status: complete ? "completed" : "running",
        ...(complete ? { result: { fen: game.fen, candidates } } : {}),
      },
    });
  });
  await page
    .getByRole("button", { name: "Deep analysis", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Cancel analysis", exact: true })
    .click();
  await expect.poll(() => cancelled).toBeGreaterThan(0);
  await expect(page.locator(".candidate-list")).toHaveCount(0);
  complete = true;
  await page
    .getByRole("button", { name: "Deep analysis", exact: true })
    .click();
  await expect(page.locator(".candidate-list .candidate")).toHaveCount(3);
});

test("guided discovery accepts a board square and restores rich messages and direct mode on reload", async ({
  page,
}) => {
  const { game, headers } = await setup(page, {
    guided_questions: true,
    visual_arrows: "on_request",
  });
  const insight = {
    id: "move-e4",
    text: "e4 controls central squares.",
    fen: game.fen,
    squares: ["e2", "e4"],
    arrows: [{ from: "e2", to: "e4" }],
  };
  let state = {
    stage: "identify",
    discovered_ids: ["exposed:e2"],
    mode: "guided",
    turns: 1,
    question: "Which piece attacks the pawn?",
  };
  let messages = [
    {
      role: "assistant",
      content: "Inspect the central pawn.",
      fen: game.fen,
      source: "deterministic",
      insights: [insight],
      variations: [],
    },
  ];
  const requests: { question: string; teaching_mode: string }[] = [];
  await page.route(`**/api/games/${game.id}/conversation?*`, (route) =>
    route.fulfill({ json: { messages, state } }),
  );
  await page.route("**/api/coach", async (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    state = {
      ...state,
      stage: "calculate",
      discovered_ids: ["exposed:e2", "attacker:d5"],
      mode: body.teaching_mode,
      turns: 2,
    };
    messages = [
      ...messages,
      {
        ...messages[0],
        content: "You selected the square; now calculate a reply.",
      },
    ];
    await route.fulfill({
      contentType: "text/event-stream",
      body: `event: done\ndata: ${JSON.stringify({ text: messages.at(-1)!.content, source: "deterministic", insights: [insight], variations: [], state })}\n\n`,
    });
  });
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Your guided discovery" }),
  ).toContainText("Identify the attacker");
  await page
    .getByRole("button", { name: "Answer by selecting a square", exact: true })
    .click();
  await page.locator('[data-testid="chessboard"] [data-square="e2"]').click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].question).toBe("e2");
  await page
    .getByLabel("Teaching style", { exact: true })
    .selectOption("direct");
  await page
    .getByRole("textbox", { name: "Ask about this position…", exact: true })
    .fill("Explain directly.");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].teaching_mode).toBe("direct");
  await page.reload();
  await expect(page.getByLabel("Teaching style", { exact: true })).toHaveValue(
    "direct",
  );
  await expect(
    page.getByRole("button", { name: "Show on board", exact: true }).first(),
  ).toBeVisible();
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.moves).toEqual([]);
});

test("playback animation and return preferences control demonstrations", async ({
  page,
}) => {
  const { preferences, game, headers } = await setup(page, {
    animate_variations: true,
    return_after_playback: true,
    variation_speed_ms: 450,
  });
  await page
    .getByRole("button", { name: "Compare 3 moves", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Preview variation", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Variation playback" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Variation playback" }),
  ).toHaveCount(0);
  preferences.animate_variations = false;
  preferences.return_after_playback = false;
  await page.reload();
  await page
    .getByRole("button", { name: "Compare 3 moves", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Preview variation", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Variation playback" }),
  ).toContainText("1 / 3");
  await expect(
    page.getByRole("button", { name: "Play variation", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Variation end", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Variation playback" }),
  ).toContainText("3 / 3");
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.moves).toEqual([]);
});

test("committing a calculated candidate rejects a stale game revision", async ({
  page,
}) => {
  const { game, headers } = await setup(page);
  await page.route("**/api/calculation", (route) =>
    route.fulfill({
      json: {
        fen: game.fen,
        text: "The line is legal.",
        first_inaccuracy_ply: null,
        steps: [],
      },
    }),
  );
  await page
    .getByRole("button", { name: "Calculate before moving", exact: true })
    .click();
  await move(page, "e2", "e4", ".calculation-board");
  await page
    .getByRole("button", { name: "Check calculation", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Play my calculated first move",
      exact: true,
    }),
  ).toBeVisible();
  const updated = await page.request.post(`/api/games/${game.id}/moves`, {
    headers,
    data: { move: "d2d4", revision: game.revision },
  });
  expect(updated.ok()).toBe(true);
  await page
    .getByRole("button", { name: "Play my calculated first move", exact: true })
    .click();
  await expect(page.locator(".error-notice")).toBeVisible();
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.moves.map((entry: { uci: string }) => entry.uci)).toEqual([
    "d2d4",
  ]);
});
