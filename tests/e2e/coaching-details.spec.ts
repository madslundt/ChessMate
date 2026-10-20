import {
  test,
  expect,
} from "../../src/frontend/node_modules/@playwright/test/index.mjs";

test("candidate trade-offs, equivalent estimates and qualified positional features remain inspectable", async ({
  page,
}) => {
  const profile = await (
    await page.request.post("/api/profiles", {
      data: {
        name: `details_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
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
  await page.addInitScript(
    (id) => localStorage.setItem("chessmate.profile", id),
    profile.id,
  );
  await page.route("**/api/profiles", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({
      json: [
        {
          ...profile,
          preferences: {
            ...profile.preferences,
            complexity: "advanced",
            visual_arrows: "on_request",
          },
        },
      ],
    });
  });
  const result = {
    fen: game.fen,
    mode: "deep",
    confidence: "search_estimate",
    candidates: [
      {
        uci: "e2e4",
        san: "e4",
        cp: 25,
        mate: null,
        pv: ["e4", "e5"],
        pv_uci: ["e2e4", "e7e5"],
        reply: "e5",
        strategy: {
          plan: "Prepare development while checking central replies.",
          advantages: ["The pawn controls d5 and f5."],
          drawbacks: ["Check the pawn’s support before advancing further."],
          qualification: "Interpretation from geometry.",
        },
      },
      {
        uci: "d2d4",
        san: "d4",
        cp: 20,
        mate: null,
        pv: ["d4", "d5"],
        pv_uci: ["d2d4", "d7d5"],
      },
    ],
    strategic_insights: [
      {
        id: "white-pawn-squares",
        claim_type: "position_fact",
        fen: game.fen,
        text: "White has pawns on d2 and e2.",
        squares: ["d2", "e2"],
        arrows: [],
      },
      {
        id: "development-plan",
        claim_type: "strategic_interpretation",
        fen: game.fen,
        text: "Consider developing a minor piece after checking forcing moves.",
        squares: [],
        arrows: [],
      },
    ],
  };
  await page.route("**/api/analysis/jobs", (route) =>
    route.fulfill({
      status: 202,
      json: { id: "detail-job", status: "queued", fen: game.fen },
    }),
  );
  await page.route("**/api/analysis/jobs/detail-job", (route) =>
    route.fulfill({
      json: { id: "detail-job", status: "completed", fen: game.fen, result },
    }),
  );
  try {
    await page.goto(`/analyze/${game.id}`);
    await page.getByRole("tab", { name: "Chat", exact: true }).click();
    await page
      .getByRole("button", { name: "Deep analysis", exact: true })
      .click();
    await expect(page.locator(".candidate-list")).toContainText(
      "Deeper-search estimate",
    );
    await expect(page.locator(".positional-insights")).toContainText(
      "Verified board feature",
    );
    await expect(page.locator(".positional-insights")).toContainText(
      "Positional interpretation",
    );
    await expect(page.locator(".candidate").first()).toContainText(
      "Opponent response: e5",
    );
    await expect(page.locator(".candidate").first()).toContainText(
      "Prepare development while checking central replies.",
    );
    await expect(page.locator(".candidate").first()).toContainText(
      "Possible positional benefits",
    );
    await expect(page.locator(".candidate").first()).toContainText(
      "Positional costs to consider",
    );
    await expect(page.locator(".candidate").nth(1)).toContainText(
      "Similar engine estimate at this search budget",
    );
    const feature = page
      .locator(".positional-insights article")
      .filter({ hasText: "White has pawns on d2 and e2." });
    await feature
      .getByRole("button", { name: "Show on board", exact: true })
      .click();
    await expect(
      page.locator('[data-square="d2"] .board-square'),
    ).toHaveAttribute("style", /box-shadow/);
    const saved = await (
      await page.request.get(`/api/games/${game.id}`, { headers })
    ).json();
    expect(saved.moves).toEqual([]);
  } finally {
    await page.request.delete(`/api/profiles/${profile.id}`);
  }
});
