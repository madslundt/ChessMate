import {
  test,
  expect,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";
import { mkdir } from "node:fs/promises";
import type { Page } from "../../src/frontend/node_modules/@playwright/test/index.mjs";
async function createProfile(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("New profile", { exact: true })
    .fill(`e2e_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`);
  const creation = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/profiles",
  );
  await page
    .getByRole("button", { name: "Create profile", exact: true })
    .click();
  const created = await creation;
  expect(created.status(), await created.text()).toBe(201);
  const headers = { "X-Profile-ID": (await created.json()).id as string };
  await expect(
    page.getByRole("button", { name: "New game", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Play" })).toBeVisible();
  // These scenarios intentionally exercise the opt-in paused-response flow.
  const paused = await page.request.patch("/api/settings", {
    headers,
    data: { auto_computer: false },
  });
  expect(paused.status()).toBe(200);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Play" })).toBeVisible();
  return headers;
}
test.afterEach(async ({ page }) => {
  const profileId = await page.evaluate(() =>
    localStorage.getItem("chessmate.profile"),
  );
  if (profileId) await page.request.delete(`/api/profiles/${profileId}`);
});
async function start(page: Page) {
  await page.getByRole("button", { name: "New game", exact: true }).click();
  await page.getByRole("button", { name: "Start game", exact: true }).click();
  await expect(
    page.getByText("Automatically saved", { exact: true }),
  ).toBeVisible();
}
async function move(page: Page, from: string, to: string) {
  const touch = await page.evaluate(() => navigator.maxTouchPoints > 0);
  for (const square of [from, to]) {
    const target = page.locator(`[data-square="${square}"]`);
    if (touch) await target.tap();
    else await target.click();
  }
}

test("complete game, coach, exploration, training and resume flow", async ({
  page,
}, info) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  const headers = await createProfile(page);
  await start(page);
  await mkdir("/tmp/chessmate-gameplay", { recursive: true });
  await page.screenshot({
    path: `/tmp/chessmate-gameplay/${info.project.name}-initial.png`,
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "e2 White p", exact: true })
    .press("Enter");
  await page.getByRole("button", { name: "e4", exact: true }).press("Enter");
  await expect(page.getByTestId("move-feedback")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Let computer move", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Let computer move", exact: true })
    .click();
  await expect(page.getByText("Your turn", { exact: true })).toBeVisible();
  const before = await page.request.get("/api/games", { headers });
  const saved = (await before.json())[0];
  expect(saved.moves).toHaveLength(2);
  await page
    .getByRole("button", { name: "Explore position", exact: true })
    .click();
  await expect(
    page.getByText("Exploring a variation", { exact: true }),
  ).toBeVisible();
  await move(page, "g1", "f3");
  await expect(
    page.getByText("Analyzing the position…", { exact: true }),
  ).not.toBeVisible();
  expect(
    (
      await (
        await page.request.get(`/api/games/${saved.id}`, { headers })
      ).json()
    ).moves,
  ).toHaveLength(2);
  await page
    .getByRole("button", { name: "Return to game", exact: true })
    .click();
  await expect(
    page.getByText("Exploring a variation", { exact: true }),
  ).not.toBeVisible();
  expect(
    (
      await (
        await page.request.get(`/api/games/${saved.id}`, { headers })
      ).json()
    ).fen,
  ).toBe(saved.fen);
  await page
    .getByRole("button", { name: "Compare 3 moves", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Preview variation", exact: true }),
  ).toHaveCount(3);
  await page
    .getByRole("button", { name: "Give me a hint", exact: true })
    .click();
  await expect(page.getByTestId("position-hint")).toBeVisible();
  await page
    .getByRole("textbox", { name: "Ask about this position…", exact: true })
    .fill("What should I focus on?");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".chat-message.assistant p")).not.toBeEmpty();
  await expect(
    page.locator(".chat-message.assistant .message-source"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Moves", exact: false })
    .first()
    .click();
  await expect(page.locator(".move-table")).toContainText("e4");
  await page.getByRole("link", { name: "Game history", exact: true }).click();
  await page.locator(".history-row").first().click();
  await expect(
    page.getByText("Automatically saved", { exact: true }),
  ).toBeVisible();
  expect(
    (
      await (
        await page.request.get(`/api/games/${saved.id}`, { headers })
      ).json()
    ).moves,
  ).toHaveLength(2);
  await page.getByRole("link", { name: "Learn", exact: true }).click();
  await page.getByRole("tab", { name: "Forks", exact: true }).click();
  await page
    .locator(".lesson-row")
    .filter({ hasText: "Knight fork: h6" })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Knight fork: h6" }),
  ).toBeVisible();
  await move(page, "f5", "h6");
  await expect(
    page.getByRole("heading", { name: "Nicely spotted." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Progress", exact: true }).click();
  await expect(page.locator(".progress-stats")).toContainText("100%");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page
    .getByLabel("Interface language", { exact: true })
    .selectOption("da");
  await page.getByLabel("Coach language", { exact: true }).selectOption("en");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Indstillinger gemt", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Lær", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lær" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `/tmp/chessmate-gameplay/${info.project.name}-learn.png`,
    fullPage: true,
  });
  expect(failures).toEqual([]);
});

test("analysis import, underpromotion, exploration commit, and persistent settings", async ({
  page,
}) => {
  const headers = await createProfile(page);
  await start(page);
  await page
    .getByRole("button", { name: "Explore position", exact: true })
    .click();
  await move(page, "d2", "d4");
  await page
    .getByRole("button", { name: "Play first move", exact: true })
    .click();
  await expect(
    page.getByText("Exploring a variation", { exact: true }),
  ).not.toBeVisible();
  const games = await (
    await page.request.get("/api/games", { headers })
  ).json();
  expect(games[0].moves[0].uci).toBe("d2d4");
  await page.reload();
  await expect(
    page.getByText("Automatically saved", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Import FEN / PGN", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "FEN / PGN", exact: true })
    .fill("7k/P7/8/8/8/8/8/7K w - - 0 1");
  await page
    .getByRole("button", { name: "Load position", exact: true })
    .click();
  await expect(page.getByText("Free analysis", { exact: true })).toBeVisible();
  await move(page, "a7", "a8");
  await page
    .getByRole("dialog", { name: "Choose a promotion" })
    .getByRole("button", { name: "n", exact: true })
    .click();
  await expect(page.getByText("Draw", { exact: true })).toBeVisible();
  const imported = await (
    await page.request.get("/api/games", { headers })
  ).json();
  expect(imported[0].moves[0].uci).toBe("a7a8n");
  const pgn = await page.request.get(`/api/games/${imported[0].id}/pgn`, {
    headers,
  });
  expect(await pgn.text()).toContain("a8=N");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("black gameplay, dark preferences, repertoire practice and saved coaching", async ({
  page,
}) => {
  const headers = await createProfile(page);
  await page.getByRole("button", { name: "New game", exact: true }).click();
  await page.getByLabel("Your color", { exact: true }).selectOption("black");
  await page.getByRole("button", { name: "Start game", exact: true }).click();
  await page
    .getByRole("button", { name: "Let computer move", exact: true })
    .click();
  await expect(page.getByText("Your turn", { exact: true })).toBeVisible();
  await move(page, "e7", "e5");
  await expect(page.getByTestId("move-feedback").last()).toBeVisible();
  await expect(page.getByTestId("move-feedback").last()).toContainText("e5");
  await page
    .getByRole("textbox", { name: "Ask about this position…", exact: true })
    .fill("Why was my last move good or bad?");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.locator(".chat-message.assistant .message-source"),
  ).toBeVisible();
  await expect(page.locator(".chat-message.assistant p")).toContainText("e5");
  await page.getByRole("link", { name: "Game history", exact: true }).click();
  await page.locator(".history-row").first().click();
  await expect(page.locator(".chat-message.assistant p")).toContainText("e5");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByLabel("Theme", { exact: true }).selectOption("dark");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("link", { name: "Learn", exact: true }).click();
  await page.getByRole("tab", { name: "Opening", exact: true }).click();
  await page.getByRole("button", { name: "Add a line", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add an opening line" });
  await dialog.getByLabel("Name", { exact: true }).fill("Italian basics");
  await dialog
    .getByLabel("Moves from the starting position (SAN or UCI)", {
      exact: true,
    })
    .fill("e4 e5 Nf3 Nc6 Bc4 Bc5");
  await dialog
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(page.locator(".repertoire-line")).toContainText(
    "Italian basics",
  );
  await page
    .locator(".repertoire-line")
    .getByRole("button", { name: "Start practice", exact: true })
    .click();
  await expect(page.locator(".objective-text")).toBeVisible();
  await move(page, "e2", "e4");
  await expect(
    page.getByRole("heading", { name: "Nicely spotted." }),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
