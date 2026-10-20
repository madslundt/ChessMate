import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';

// Separate optional-mode server keeps default trusted-profile regressions intact.
test('authenticated accounts sign in, survive reload, change passwords and revoke sessions', async ({ page }) => {
  const base = process.env.E2E_SECURE_BASE_URL;
  test.skip(!base, 'Requires an isolated SECURE_DEPLOYMENT=true server');
  const endpoint = (path: string) => new URL(path, base).toString();
  const name = `secure_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const password = 'a long secure testing password';
  await page.goto(base!);
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Create an account', exact: true }).click();
  await page.getByLabel('Profile name', { exact: true }).fill(name);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
  const profileId = await page.evaluate(() => localStorage.getItem('chessmate.profile'));
  try {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Play', exact: true })).toBeVisible();
    const cookies = await page.context().cookies();
    expect(cookies.find((cookie) => cookie.name === 'chessmate_session')).toMatchObject({ httpOnly: true, sameSite: 'Strict' });
    expect((await page.request.get(endpoint('/api/settings'), { headers: { 'X-Profile-ID': 'someone-else' } })).status()).toBe(403);
    await page.getByRole('link', { name: 'Settings', exact: true }).click();
    await page.getByLabel('Current password', { exact: true }).fill(password);
    const changed = 'another long secure testing password';
    await page.getByLabel('New password', { exact: true }).fill(changed);
    await page.getByLabel('Repeat password', { exact: true }).fill(changed);
    await page.getByRole('button', { name: 'Change password', exact: true }).click();
    await expect(page.getByText('Password changed.', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Sign out', exact: true }).first().click();
    await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
    expect((await page.request.get(endpoint('/api/settings'))).status()).toBe(401);
    await page.getByLabel('Profile name', { exact: true }).fill(name);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByText('Incorrect profile name or password', { exact: true })).toBeVisible();
    await page.getByLabel('Password', { exact: true }).fill(changed);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  } finally {
    if (profileId) await page.request.delete(endpoint(`/api/profiles/${profileId}`));
  }
});
