import {
  test,
  expect,
  type Page,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";
async function profile(page: Page, preferences: Record<string, unknown> = {}) {
  const created = await page.request.post("/api/profiles", {
    data: {
      name: `realcoach_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    },
  });
  expect(created.ok()).toBe(true);
  const user = await created.json();
  const headers = { "X-Profile-ID": user.id };
  const settings = await page.request.patch("/api/settings", {
    headers,
    data: {
      play_mode: "coach_first",
      auto_computer: false,
      skill_defaults: false,
      analysis_time_ms: 100,
      ...preferences,
    },
  });
  expect(settings.ok()).toBe(true);
  await page.addInitScript(
    (id) => localStorage.setItem("chessmate.profile", id),
    user.id,
  );
  return headers;
}
async function chat(page: Page, id: string) {
  await page.goto(`/analyze/${id}`);
  await page.getByRole("tab", { name: "Chat", exact: true }).click();
}
async function send(page: Page, question: string) {
  await page
    .getByRole("textbox", { name: "Ask about this position…", exact: true })
    .fill(question);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
}
test.afterEach(async ({ page }) => {
  const id = await page.evaluate(() =>
    localStorage.getItem("chessmate.profile"),
  );
  if (id) await page.request.delete(`/api/profiles/${id}`);
});

test("real guided coaching preserves discoveries, visual evidence and direct mode after reload", async ({
  page,
}) => {
  const headers = await profile(page, {
    coaching_mode: "socratic",
    guided_questions: true,
    visual_arrows: "on_request",
  });
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", fen: "4k3/8/8/8/4r3/8/4B3/6K1 w - - 0 1" },
    })
  ).json();
  await chat(page, game.id);
  await page
    .getByRole("button", { name: "Answer by selecting a square", exact: true })
    .click();
  await page.locator('[data-testid="chessboard"] [data-square="e2"]').click();
  await expect(
    page.getByRole("region", { name: "Your guided discovery" }),
  ).toContainText("Identify the attacker");
  await page
    .getByRole("button", { name: "Answer by selecting a square", exact: true })
    .click();
  await page.locator('[data-testid="chessboard"] [data-square="e4"]').click();
  await expect(
    page.getByRole("region", { name: "Your guided discovery" }),
  ).toContainText("Calculate a response");
  await send(page, "What if Bf3? Show me the line.");
  await expect(
    page
      .locator(".chat-message.assistant .visual-explanation-actions")
      .last()
      .getByRole("button")
      .first(),
  ).toBeVisible();
  const before = await (
    await page.request.get(`/api/games/${game.id}/conversation`, { headers })
  ).json();
  expect(before.state.discovered_ids).toContain("exposed:e2");
  expect(before.state.discovered_ids).toContain("attacker:e2:e4");
  expect(before.messages.at(-1).insights.length).toBeGreaterThan(0);
  await page
    .getByLabel("Teaching style", { exact: true })
    .selectOption("direct");
  await send(page, "Explain directly.");
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/games/${game.id}/conversation`, {
              headers,
            })
          ).json()
        ).state?.mode,
    )
    .toBe("direct");
  await chat(page, game.id);
  await expect(page.getByLabel("Teaching style", { exact: true })).toHaveValue(
    "direct",
  );
  await expect(
    page
      .locator(".chat-message.assistant .visual-explanation-actions")
      .filter({ has: page.getByRole("button") })
      .first(),
  ).toBeVisible();
  const after = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(after.moves).toEqual([]);
  expect(after.revision).toBe(game.revision);
});

test("a real deep search stops on cancellation and the player can still make a saved move", async ({
  page,
}) => {
  const headers = await profile(page, { deep_analysis_time_ms: 20000 });
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis" },
    })
  ).json();
  await chat(page, game.id);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/analysis/jobs",
  );
  await page
    .getByRole("button", { name: "Deep analysis", exact: true })
    .click();
  const response = await created;
  expect(response.status()).toBe(202);
  const job = await response.json();
  await page
    .getByRole("button", { name: "Cancel analysis", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/analysis/jobs/${job.id}`, { headers })
          ).json()
        ).status,
    )
    .toBe("cancelled");
  await page.locator('[data-testid="chessboard"] [data-square="e2"]').click();
  await page.locator('[data-testid="chessboard"] [data-square="e4"]').click();
  await expect(page.getByTestId("move-feedback")).toBeVisible();
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.moves.map((move: { uci: string }) => move.uci)).toEqual([
    "e2e4",
  ]);
});

test("full-game background analysis can be cancelled, resumed and rechecks critical decisions", async ({
  page,
}) => {
  const headers = await profile(page, { deep_analysis_time_ms: 5000 });
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", pgn: "1. f3 e5 2. g4 Qh4# 0-1" },
    })
  ).json();
  await page.goto(`/analyze/${game.id}`);
  // Keep creation pending until cancellation is requested, even when all engine
  // positions are cached and the real background job finishes immediately.
  let releaseCreation: () => void = () => undefined;
  const creationHeld = new Promise<void>((resolve) => {
    releaseCreation = resolve;
  });
  await page.route(
    `**/api/games/${game.id}/analysis-jobs`,
    async (route) => {
      const response = await route.fetch();
      await creationHeld;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname ===
        `/api/games/${game.id}/analysis-jobs`,
  );
  await page
    .getByRole("button", { name: "Analyze every move", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Cancel analysis", exact: true })
    .click();
  releaseCreation();
  const job = await (await created).json();
  await expect
    .poll(
      async () =>
        (
          await (
            await page.request.get(`/api/analysis/jobs/${job.id}`, { headers })
          ).json()
        ).status,
    )
    .toMatch(/^(cancelled|completed)$/);
  await expect(
    page.getByRole("button", { name: "Analyze every move", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Analyze every move", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Analyze every move", exact: true }),
  ).toBeEnabled({ timeout: 45000 });
  await expect(page.locator('.game-review [role="status"]')).toContainText(
    "4 / 4",
  );
  await expect(page.locator('.game-review [role="status"]')).toContainText(
    /Critical decisions rechecked: [1-9]/,
  );
  const saved = await (
    await page.request.get(`/api/games/${game.id}`, { headers })
  ).json();
  expect(saved.fen).toBe(game.fen);
  expect(saved.moves).toHaveLength(4);
  expect(
    saved.moves.every((move: { feedback?: unknown }) => move.feedback),
  ).toBe(true);
  expect(saved.moves[2].feedback.classification).toBe("Blunder");
  expect(saved.moves[2].feedback.confidence).toBe("rechecked_estimate");
});

test("cancelling before a game-analysis creation response arrives cannot orphan or replace the next job", async ({
  page,
}) => {
  const headers = await profile(page);
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis", pgn: "1. e4 e5 *" },
    })
  ).json();
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requests = 0;
  const cancelled: string[] = [];
  await page.route(`**/api/games/${game.id}/analysis-jobs`, async (route) => {
    const request = ++requests;
    if (request === 1) await held;
    await route.fulfill({
      status: 202,
      json: {
        id: request === 1 ? "late-game-job" : "current-game-job",
        status: "queued",
        fen: game.fen,
      },
    });
  });
  await page.route("**/api/analysis/jobs/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-1)!;
    if (route.request().method() === "DELETE") {
      cancelled.push(id);
      return route.fulfill({
        json: { id, status: "cancelled", fen: game.fen },
      });
    }
    return route.fulfill({
      json: {
        id,
        status: "running",
        fen: game.fen,
        progress: { completed: 0, total: 2, critical_verified: 0 },
      },
    });
  });
  await page.goto(`/analyze/${game.id}`);
  await page
    .getByRole("button", { name: "Analyze every move", exact: true })
    .click();
  await expect.poll(() => requests).toBe(1);
  await page
    .getByRole("button", { name: "Cancel analysis", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Analyze every move", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Analyze every move", exact: true })
    .click();
  await expect.poll(() => requests).toBe(2);
  release();
  await expect.poll(() => cancelled.includes("late-game-job")).toBe(true);
  await page
    .getByRole("button", { name: "Cancel analysis", exact: true })
    .click();
  await expect.poll(() => cancelled.includes("current-game-job")).toBe(true);
});
