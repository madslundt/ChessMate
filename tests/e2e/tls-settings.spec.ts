import { test, expect } from '../../src/frontend/node_modules/@playwright/test/index.mjs';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:https';
import { mkdtemp, readFile, rm, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { AddressInfo } from 'node:net';

test('certificate verification defaults on; explicit ignore persists and resets for a new endpoint', async ({
  page,
}, info) => {
  const directory = await mkdtemp(join(tmpdir(), 'chessmate-tls-browser-'));
  const certificate = join(directory, 'certificate.pem');
  const key = join(directory, 'key.pem');
  execFileSync(
    'openssl',
    [
      'req',
      '-x509',
      '-newkey',
      'rsa:2048',
      '-nodes',
      '-days',
      '1',
      '-subj',
      '/CN=localhost',
      '-addext',
      'subjectAltName=DNS:localhost',
      '-keyout',
      key,
      '-out',
      certificate,
    ],
    { stdio: 'ignore' },
  );
  const server = createServer({ key: await readFile(key), cert: await readFile(certificate) }, (_request, response) => {
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ data: [{ id: 'self-signed-model' }] }));
  });
  await new Promise<void>((resolve) => server.listen(0, '0.0.0.0', resolve));
  let profileId: string | undefined;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    const created = await page.request.post('/api/profiles', {
      data: { name: `TLS ${Date.now()} ${info.project.name}` },
    });
    expect(created.status()).toBe(201);
    profileId = (await created.json()).id;
    await page.addInitScript((id) => localStorage.setItem('chessmate.profile', id), profileId!);
    await page.goto('/');
    await expect(page).toHaveTitle(/Chessmate/);
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const mode = page.getByLabel('HTTPS certificate', { exact: true });
    await expect(mode).toHaveValue('verify');
    const endpoint = `https://${process.env.E2E_MODEL_HOST || 'host.docker.internal'}:${(server.address() as AddressInfo).port}/v1`;
    await page.getByLabel('LLM endpoint', { exact: true }).fill(endpoint);
    await expect(
      page.getByText(
        'The backend does not trust this server’s TLS certificate. Add its local CA certificate to the backend trust bundle.',
        { exact: true },
      ),
    ).toBeVisible();
    await mode.selectOption('ignore');
    await expect(page.getByText('Available models loaded from your endpoint.', { exact: true })).toBeVisible();
    await expect(page.locator('.llm-certificate-warning')).toBeVisible();
    await page.getByLabel('Model', { exact: true }).selectOption({ label: 'self-signed-model' });
    await page.getByRole('button', { name: 'Save connection', exact: true }).click();
    await expect(page.getByText('Connection saved', { exact: true })).toBeVisible();
    const saved = await page.request.get('/api/settings/llm', { headers: { 'X-Profile-ID': profileId! } });
    expect((await saved.json()).verify_tls).toBe(false);
    await page.reload();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(mode).toHaveValue('ignore');
    await expect(page.getByText('Available models loaded from your endpoint.', { exact: true })).toBeVisible();
    await mkdir('/tmp/chessmate-tls-settings', { recursive: true });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `/tmp/chessmate-tls-settings/${info.project.name}.png` });
    await page.getByLabel('LLM endpoint', { exact: true }).fill(endpoint.replace('/v1', '/another/v1'));
    await expect(mode).toHaveValue('verify');
    await expect(page.locator('.llm-certificate-warning')).toHaveCount(0);
    await expect(
      page.getByText(
        'The backend does not trust this server’s TLS certificate. Add its local CA certificate to the backend trust bundle.',
        { exact: true },
      ),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  } finally {
    if (profileId) await page.request.delete(`/api/profiles/${profileId}`);
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  }
});
