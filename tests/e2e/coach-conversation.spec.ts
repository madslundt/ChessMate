import { test, expect, type Page } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

async function setup(page: Page) {
  const profile = await (await page.request.post('/api/profiles', { data: { name: `conversation_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` } })).json();
  const headers = { 'X-Profile-ID': profile.id };
  await page.request.patch('/api/settings', { headers, data: { coach_language: 'da', visual_arrows: 'automatic', explanation_mode: 'both' } });
  await page.request.patch('/api/settings/llm', { headers, data: { base_url: '', model: '' } });
  const game = await (await page.request.post('/api/games', { headers, data: { mode: 'analysis', fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2' } })).json();
  await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), profile.id);
  await page.goto(`/analyze/${game.id}`);
  await page.getByRole('tab', { name: 'Chat', exact: true }).click();
  return { profile, game, headers };
}

async function ask(page: Page, question: string, count: number) {
  await page.locator('#coach-question').fill(question);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('.chat-message.assistant')).toHaveCount(count);
  await expect(page.locator('.chat-message.assistant').last().locator('.message-source')).toBeVisible();
}

async function move(page: Page, from: string, to: string) {
  for (const square of [from, to]) await page.locator(`[data-square="${square}"]`).click();
}

test('short follow-ups and reloaded board hints retain the same development idea', async ({ page }, testInfo) => {
  const { profile, game, headers } = await setup(page);
  try {
    await ask(page, 'Skal jeg udvikle hesten eller løberen først?', 1);
    const saved = await (await page.request.get(`/api/games/${game.id}/conversation`, { headers })).json();
    const first = saved.messages.find((entry: { role: string }) => entry.role === 'assistant');
    const focus = first.insights[0].arrows[0];
    await ask(page, 'Hvorfor?', 2);
    await expect(page.locator('.chat-message.assistant').last()).toContainText('Pointen med');
    await expect(page.locator(`path[marker-end*="${focus.from}-${focus.to}"]`)).toHaveCount(1);
    await page.reload();
    await page.getByRole('tab', { name: 'Chat', exact: true }).click();
    await expect(page.locator('.chat-message.assistant')).toHaveCount(2);
    await ask(page, 'Uddyb', 3);
    await expect(page.locator('.chat-message.assistant').last()).toContainText('Pointen med');
    await page.getByRole('button', { name: 'Give me a hint', exact: true }).click();
    await expect(page.getByTestId('position-hint')).toContainText('1/2');
    await expect(page.locator(`[data-square="${focus.from}"] .board-square`)).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
    await page.getByRole('button', { name: /Next hint/ }).click();
    await expect(page.getByTestId('position-hint')).toContainText('2/2');
    await expect(page.locator(`path[marker-end*="${focus.from}-${focus.to}"]`)).toHaveCount(1);
    await page.screenshot({ path: `/tmp/chessmate-follow-up-${testInfo.project.name}.png`, fullPage: true });
  } finally { await page.request.delete(`/api/profiles/${profile.id}`, { headers }); }
});

test('moves follow earlier messages and the complete conversation keeps its order after reload', async ({ page }, testInfo) => {
  const { profile, headers } = await setup(page);
  const entries = () => page.locator('.coach-scroll .chat-message, .coach-scroll .move-feedback-entry');
  const kinds = () => entries().evaluateAll((elements) => elements.map((element) => element.classList.contains('move-feedback-entry') ? 'move' : element.classList.contains('user') ? 'user' : 'assistant'));
  try {
    await ask(page, 'Skal jeg udvikle springeren eller løberen først?', 1);
    await move(page, 'g1', 'f3');
    await expect(page.getByTestId('move-feedback')).toHaveCount(1);
    expect(await kinds()).toEqual(['user', 'assistant', 'move']);
    await ask(page, 'Hvad bør jeg undersøge nu?', 2);
    expect(await kinds()).toEqual(['user', 'assistant', 'move', 'user', 'assistant']);
    await page.request.patch('/api/settings', { headers, data: { feedback: 'none' } });
    await move(page, 'b8', 'c6');
    await expect(page.getByTestId('move-feedback')).toHaveCount(2);
    expect(await kinds()).toEqual(['user', 'assistant', 'move', 'user', 'assistant', 'move']);
    await page.reload();
    await page.getByRole('tab', { name: 'Chat', exact: true }).click();
    await expect(page.locator('.chat-message.assistant')).toHaveCount(2);
    expect(await kinds()).toEqual(['user', 'assistant', 'move', 'user', 'assistant', 'move']);
    await expect(entries().last()).toContainText('Nc6');
    const atBottom = await page.locator('.coach-scroll').evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight < 3);
    expect(atBottom).toBe(true);
    await page.screenshot({ path: `/tmp/chessmate-timeline-${testInfo.project.name}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Starting position', exact: true }).click();
    await ask(page, 'Hvorfor?', 3);
    expect(await kinds()).toEqual(['user', 'assistant', 'move', 'user', 'assistant', 'move', 'user', 'assistant']);
  } finally { await page.request.delete(`/api/profiles/${profile.id}`, { headers }); }
});
