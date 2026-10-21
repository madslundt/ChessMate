import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

test('piece-choice answers connect to board arrows and exactly two contextual hints', async ({ page }, testInfo) => {
  const profileResponse = await page.request.post('/api/profiles', {
    data: { name: `choice_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` },
  });
  expect(profileResponse.status()).toBe(201);
  const profile = await profileResponse.json();
  const headers = { 'X-Profile-ID': profile.id };
  await page.request.patch('/api/settings', { headers, data: { coach_language: 'da', explanation_mode: 'both', visual_arrows: 'automatic' } });
  await page.request.patch('/api/settings/llm', { headers, data: { base_url: '', model: '' } });
  const game = await (await page.request.post('/api/games', {
    headers, data: { mode: 'analysis', fen: 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2' },
  })).json();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), profile.id);
  try {
    await page.goto(`/analyze/${game.id}`);
    await expect(page).toHaveTitle(/Chessmate/i);
    await page.getByRole('tab', { name: 'Chat', exact: true }).click();
    await page.locator('#coach-question').fill('Skal jeg udvikle hesten eller løberen først?');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    const message = page.locator('.chat-message.assistant').last();
    await expect(message).toContainText('springer');
    await expect(message).toContainText('løber');
    await expect(message).not.toContainText('Hvilke lovlige skakker og slag');
    const boardButtons = message.getByRole('button', { name: /Show on board/ });
    await expect(boardButtons).toHaveCount(2);
    // Read saved evidence through the API: Chromium cannot always retrieve a
    // streamed response body after the production service worker consumes it.
    const conversation = await (await page.request.get(`/api/games/${game.id}/conversation`, { headers })).json();
    const answer = conversation.messages.find((entry: { role: string }) => entry.role === 'assistant');
    expect(answer).toBeTruthy();
    await boardButtons.nth(1).click();
    const alternative = answer.insights[1].arrows[0];
    await expect(page.locator(`path[marker-end*="${alternative.from}-${alternative.to}"]`)).toHaveCount(1);
    await page.getByRole('button', { name: 'Give me a hint', exact: true }).click();
    await expect(page.getByTestId('position-hint')).toContainText('1/2');
    const firstSource = answer.insights[0].arrows[0].from;
    await expect(page.locator(`[data-square="${firstSource}"] .board-square`)).toHaveCSS('box-shadow', 'rgb(213, 148, 49) 0px 0px 0px 4px inset');
    await page.getByRole('button', { name: /Next hint/ }).click();
    await expect(page.getByTestId('position-hint')).toContainText('2/2');
    await expect(page.getByRole('button', { name: /Next hint/ })).toBeDisabled();
    await page.getByTestId('position-hint').getByRole('button', { name: 'Show on board', exact: true }).click();
    await expect(page.locator(`path[marker-end*="${firstSource}-${answer.insights[0].arrows[0].to}"]`)).toHaveCount(1);
    const saved = await (await page.request.get(`/api/games/${game.id}`, { headers })).json();
    expect(saved.fen).toBe(game.fen);
    expect(saved.moves).toEqual([]);
    expect(errors).toEqual([]);
    await page.screenshot({ path: `/tmp/chessmate-piece-choice-${testInfo.project.name}.png`, fullPage: true });
  } finally {
    await page.request.delete(`/api/profiles/${profile.id}`, { headers });
  }
});
