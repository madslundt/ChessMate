import { test, expect, type Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

async function move(page: Page, from: string, to: string) {
  const touch = await page.evaluate(() => navigator.maxTouchPoints > 0);
  for (const square of [from, to]) {
    const target = page.locator(`[data-square="${square}"]`);
    if (touch) await target.tap();
    else await target.click();
  }
}

test('learning keeps continuation hints and visual playback synchronized, and saves coaching preferences', async ({
  page,
}) => {
  const response = await page.request.post('/api/profiles', {
    data: { name: `learning_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` },
  });
  expect(response.status()).toBe(201);
  const profile = await response.json();
  const headers = { 'X-Profile-ID': profile.id as string };
  await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), profile.id);
  try {
    await page.goto('/learn/forks/exercises/forks-08');
    await expect(page.getByRole('heading', { name: 'Knight fork: b5' })).toBeVisible();
    await move(page, 'a7', 'b5');
    await expect(page.locator('[data-square="b5"] [data-piece="bN"]')).toHaveCount(1);
    await expect(page.locator('[data-square="e5"] [data-piece="wK"]')).toHaveCount(1);
    for (let level = 1; level <= 4; level++) {
      const hintResponse = page.waitForResponse((result) => result.url().endsWith('/forks-08/hint'));
      await page
        .getByRole('button', { name: level === 1 ? 'Give me a hint' : 'Next hint', exact: true })
        .click();
      const hint = await (await hintResponse).json();
      if (level === 1) {
        expect(hint.highlight_square).toBe('b5');
        await expect(page.locator('[data-square="b5"] .board-square')).toHaveCSS(
          'box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset',
        );
        await expect(page.locator('path[marker-end*="b5-c7"]')).toHaveCount(0);
      } else {
        expect(hint.move).toBe('b5c7');
        await expect(page.locator('path[marker-end*="b5-c7"]')).toHaveCount(1);
        await expect(page.locator('[data-square="b5"] .board-square')).toHaveCSS('box-shadow', 'none');
      }
      if (level === 1) expect(hint.move).toBeUndefined();
    }
    await move(page, 'b5', 'c7');
    await expect(page.getByText('Solved with help or after a retry', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Show on board', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Reset', exact: true })).toBeDisabled();
    await expect(page.locator('[data-square="a7"] [data-piece="bN"]')).toHaveCount(1);
    await page.getByRole('button', { name: 'Next variation move', exact: true }).click();
    await expect(page.locator('[data-square="b5"] [data-piece="bN"]')).toHaveCount(1);
    await page.getByRole('button', { name: 'Variation end', exact: true }).click();
    await expect(page.locator('[data-square="c7"] [data-piece="bN"]')).toHaveCount(1);
    await page.getByRole('button', { name: 'Return to exercise', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Reset', exact: true })).toBeEnabled();
    const progress = await (await page.request.get('/api/progress', { headers })).json();
    expect(progress.attempts).toBe(1);
    expect(progress.topics.find((topic: { topic: string }) => topic.topic === 'forks').independent).toBe(0);
    expect(await (await page.request.get('/api/games', { headers })).json()).toHaveLength(0);

    await page.goto('/settings');
    await page.getByLabel('Play pace', { exact: true }).selectOption('coach_first');
    await page.getByLabel('Preferred explanation', { exact: true }).selectOption('both');
    await page.getByLabel('Coaching arrows', { exact: true }).selectOption('on_request');
    await page.getByLabel('Variation speed (milliseconds per move)', { exact: true }).fill('1200');
    await page.getByRole('switch', { name: 'Highlight important pieces', exact: true }).uncheck();
    await page.getByRole('switch', { name: 'Highlight verified threats', exact: true }).uncheck();
    await page.getByRole('switch', { name: 'Animate suggested variations', exact: true }).uncheck();
    await page.getByRole('switch', { name: 'Return to the original position after playback', exact: true }).uncheck();
    await page.getByLabel('Deep analysis budget (milliseconds)', { exact: true }).fill('10000');
    await page.getByLabel('Explanation complexity', { exact: true }).selectOption('advanced');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await expect(page.getByText('Preferences saved', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Play pace', { exact: true })).toHaveValue('coach_first');
    await expect(page.getByLabel('Coaching arrows', { exact: true })).toHaveValue('on_request');
    await expect(page.getByLabel('Variation speed (milliseconds per move)', { exact: true })).toHaveValue(
      '1200',
    );
    await expect(page.getByRole('switch', { name: 'Highlight important pieces', exact: true })).not.toBeChecked();
    await expect(page.getByRole('switch', { name: 'Highlight verified threats', exact: true })).not.toBeChecked();
    await expect(page.getByRole('switch', { name: 'Animate suggested variations', exact: true })).not.toBeChecked();
    await expect(page.getByRole('switch', { name: 'Return to the original position after playback', exact: true })).not.toBeChecked();
    await expect(page.getByLabel('Deep analysis budget (milliseconds)', { exact: true })).toHaveValue('10000');
    await expect(page.getByLabel('Maximum explanation length', { exact: true })).toHaveValue('300');
    await expect(page.getByRole('switch', { name: 'Show concrete variations', exact: true })).toBeChecked();
    await page.getByLabel('Maximum explanation length', { exact: true }).fill('95');
    await page.getByLabel('Explanation complexity', { exact: true }).selectOption('beginner');
    await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
    await expect(page.getByText('Preferences saved', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Maximum explanation length', { exact: true })).toHaveValue('95');
    await expect(page.getByRole('switch', { name: 'Use recommended coaching settings for my level', exact: true })).not.toBeChecked();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  } finally {
    await page.request.delete(`/api/profiles/${profile.id}`);
  }
});

test('calculation evidence persists in progress with isolated replay and comparison', async ({ page }) => {
  const created = await page.request.post('/api/profiles', { data: { name: `calculation_${Date.now()}_${Math.random().toString(36).slice(2, 7)}` } });
  expect(created.status()).toBe(201);
  const profile = await created.json();
  const headers = { 'X-Profile-ID': profile.id as string };
  await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), profile.id);
  try {
    const calculation = await page.request.post('/api/calculation', { headers, data: {
      fen: '6k1/5ppp/8/8/8/q7/1P3PPP/4R1K1 b - - 0 1', moves: ['a3b2', 'e1e8'], expected_evaluation: 'winning',
    } });
    expect(calculation.status(), await calculation.text()).toBe(200);
    const result = await calculation.json();
    expect(result.first_inaccuracy_ply).toBe(1);
    expect(result.event_id).toBeTruthy();
    await page.goto('/progress');
    await expect(page.getByRole('heading', { name: 'Calculation practice', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Observed learning patterns', exact: true })).toBeVisible();
    await page.getByRole('button').filter({ hasText: '2 predicted moves' }).click();
    await expect(page.locator('[data-square="a3"] [data-piece="bQ"]')).toHaveCount(1);
    await page.getByRole('button', { name: 'Next variation move', exact: true }).click();
    await expect(page.locator('[data-square="b2"] [data-piece="bQ"]')).toHaveCount(1);
    await page.getByRole('button', { name: 'Compare the verified alternative', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Engine comparison', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Return to your calculation', exact: true }).click();
    expect(await (await page.request.get('/api/games', { headers })).json()).toHaveLength(0);
    await page.reload();
    await expect(page.getByRole('button').filter({ hasText: '2 predicted moves' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  } finally { await page.request.delete(`/api/profiles/${profile.id}`); }
});
