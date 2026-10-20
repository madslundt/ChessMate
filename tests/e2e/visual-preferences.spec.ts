import {
  test,
  expect,
  type Page,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";
async function setup(page: Page) {
  const profile = await (
    await page.request.post("/api/profiles", {
      data: {
        name: `visualprefs_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      },
    })
  ).json();
  const headers = { "X-Profile-ID": profile.id };
  const game = await (
    await page.request.post("/api/games", {
      headers,
      data: { mode: "analysis" },
    })
  ).json();
  const preferences = {
    ...profile.preferences,
    visual_arrows: "automatic",
    explanation_mode: "both",
    highlight_threats: false,
    highlight_pieces: false,
    play_mode: "coach_first",
    auto_computer: false,
  };
  await page.addInitScript(
    (id) => localStorage.setItem("chessmate.profile", id),
    profile.id,
  );
  await page.route("**/api/profiles", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({ json: [{ ...profile, preferences }] });
  });
  await page.route(`**/api/games/${game.id}/conversation?*`, (route) =>
    route.fulfill({
      json: {
        messages: [
          {
            role: "assistant",
            content: "Inspect the central pawn before deciding.",
            fen: game.fen,
            source: "deterministic",
            insights: [
              {
                id: "central-threat",
                claim_type: "threat",
                text: "Consider the central advance.",
                fen: game.fen,
                squares: ["e2", "e4"],
                arrows: [{ from: "e2", to: "e4", color: "red" }],
              },
            ],
            variations: [],
          },
        ],
      },
    }),
  );
  async function open() {
    await page.goto(`/analyze/${game.id}`);
    await page.getByRole("tab", { name: "Chat", exact: true }).click();
    await expect(page.locator(".chat-message.assistant")).toContainText(
      "Inspect the central pawn before deciding.",
    );
  }
  await open();
  return { preferences, open };
}
test.afterEach(async ({ page }) => {
  const id = await page.evaluate(() =>
    localStorage.getItem("chessmate.profile"),
  );
  if (id) await page.request.delete(`/api/profiles/${id}`);
});

test("threat arrows and mentioned-piece highlights can be enabled independently", async ({
  page,
}) => {
  const { preferences, open } = await setup(page);
  const arrow = page.locator('path[marker-end*="e2-e4"]');
  const target = page.locator('[data-square="e4"] .board-square');
  await expect(arrow).toHaveCount(0);
  await expect(target).not.toHaveAttribute("style", /box-shadow/);
  preferences.highlight_threats = true;
  await open();
  await expect(arrow).toBeAttached();
  await expect(target).not.toHaveAttribute("style", /box-shadow/);
  preferences.highlight_pieces = true;
  await open();
  await expect(arrow).toBeAttached();
  await expect(target).toHaveAttribute("style", /box-shadow/);
});

test("board-first mode collapses prose while text-first mode keeps prose and hides automatic overlays", async ({
  page,
}) => {
  const { preferences, open } = await setup(page);
  preferences.explanation_mode = "visual";
  preferences.highlight_threats = true;
  await open();
  await expect(
    page.getByText("Inspect the central pawn before deciding.", {
      exact: true,
    }),
  ).not.toBeVisible();
  await page.getByText("Read the explanation", { exact: true }).click();
  await expect(
    page.getByText("Inspect the central pawn before deciding.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator('path[marker-end*="e2-e4"]')).toBeAttached();
  preferences.explanation_mode = "text";
  await open();
  await expect(
    page.getByText("Inspect the central pawn before deciding.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page
      .locator(".chat-message.assistant")
      .getByRole("button", { name: "Show on board", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator('path[marker-end*="e2-e4"]')).toHaveCount(0);
});
