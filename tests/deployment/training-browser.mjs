/** Supplemental checks against an already-running production deployment.
 * DEPLOY_BASE_URL=http://127.0.0.1:8080 node tests/deployment/training-browser.mjs
 * Optional: DEPLOY_DEVICE=mobile DEPLOY_ARTIFACT_DIR=/tmp/chessmate-deployment
 * Creates one isolated test account and two private repertoire lines.
 */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium, devices } from '../../src/frontend/node_modules/playwright/index.mjs';
import { Chess } from '../../src/frontend/node_modules/chess.js/dist/esm/chess.js';

const baseURL = (process.env.DEPLOY_BASE_URL || process.env.E2E_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');
const mobile = process.env.DEPLOY_DEVICE === 'mobile';
const directory = process.env.DEPLOY_ARTIFACT_DIR || '/tmp/chessmate-deployment';
const stages = [];
const seed = JSON.parse(await readFile(new URL('../../src/backend/exercise_library.json', import.meta.url), 'utf8'));
const browser = await chromium.launch();
let context;
try {
  context = await browser.newContext({
    baseURL,
    ...(mobile ? devices['iPhone 13'] : { viewport: { width: 1488, height: 1058 } }),
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(30000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  async function json(path, data) {
    const response = data === undefined
      ? await context.request.get(path)
      : await context.request.post(path, { data });
    assert(response.ok(), `${path}: HTTP ${response.status()} ${await response.text()}`);
    return response.json();
  }
  async function move(uci) {
    for (const square of [uci.slice(0, 2), uci.slice(2, 4)]) {
      const cell = page.locator(`[data-square="${square}"]`);
      if (mobile) await cell.tap();
      else await cell.click();
    }
  }
  async function attempt(uci, exerciseId) {
    const pending = page.waitForResponse((response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/exercises/${exerciseId}/attempt`,
    );
    await move(uci);
    const response = await pending;
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  }
  async function openLesson(exercise) {
    await page.locator('.lesson-row').filter({ hasText: exercise.title }).first().click();
    await page.getByRole('heading', { name: exercise.title, exact: true }).waitFor();
  }
  async function assertStats(expected) {
    await page.getByRole('button', { name: 'Progress', exact: true }).click();
    await page.getByRole('heading', { name: 'Progress', exact: true }).waitFor();
    for (const [label, value] of Object.entries(expected)) {
      const stat = page.locator('.stat').filter({ has: page.getByText(label, { exact: true }) }).locator('strong');
      await stat.waitFor();
      assert.equal(await stat.innerText(), String(value), `${label} did not match persisted learning events`);
    }
  }

  await page.goto('/');
  const account = `dep_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
  await json('/api/auth/register', { name: account, password: 'deployment-training-test-only' });
  await page.reload();
  await page.getByRole('heading', { name: 'Play', exact: true }).waitFor();
  const exercises = await json('/api/exercises');
  assert(exercises.length >= 64, 'The enriched 64-position curriculum must be seeded');
  assert(exercises.every((exercise) => exercise.description && !exercise.solution && !exercise.evidence));
  const first = exercises.find((exercise) => exercise.id === 'forks-01');
  const multi = exercises.find((exercise) => exercise.id === 'forks-08');
  assert(first && multi);
  const solution = seed.find((exercise) => exercise.id === first.id).solution;
  const variation = seed.find((exercise) => exercise.id === multi.id).solution;
  assert.equal(variation.length, 3);
  assert.equal((await json('/api/progress')).attempts, 0);
  stages.push('isolated authenticated account and enriched public curriculum');

  await page.getByRole('button', { name: 'Learn', exact: true }).click();
  await page.getByRole('tab', { name: 'Forks', exact: true }).click();
  await openLesson(first);
  const wrong = new Chess(first.fen).moves({ verbose: true }).find((candidate) => candidate.piece === 'k');
  assert(wrong, 'The regression position must allow a harmless incorrect king move');
  const rejected = await attempt(wrong.from + wrong.to, first.id);
  assert.equal(rejected.correct, false);
  assert.equal(rejected.complete, false);
  assert.equal(rejected.fen, first.fen);
  assert(!('solution' in rejected), 'A wrong answer must not reveal the solution');
  await page.getByRole('heading', { name: 'Try another idea', exact: true }).waitFor();
  for (let level = 1; level <= 4; level++) {
    await page.getByRole('button', { name: level === 1 ? 'Give me a hint' : 'Next hint', exact: true }).click();
    await page.locator('.hint-note').getByText(`Give me a hint ${level}/4`, { exact: true }).waitFor();
  }
  const assisted = await attempt(solution[0], first.id);
  assert(assisted.correct && assisted.complete);
  assert.equal(assisted.hint_level, 4);
  await page.getByRole('heading', { name: 'Nicely spotted.', exact: true }).waitFor();
  stages.push('incorrect move resets board without spoilers; four progressive hints; assisted solve');

  await page.getByRole('button', { name: 'Back to lessons', exact: true }).click();
  await openLesson(multi);
  const partial = await attempt(variation[0], multi.id);
  assert(partial.correct && !partial.complete);
  assert.equal(partial.reply, variation[1]);
  await page.getByRole('heading', { name: 'Continue', exact: true }).waitFor();
  const finished = await attempt(variation[2], multi.id);
  assert(finished.correct && finished.complete);
  await page.getByRole('heading', { name: 'Nicely spotted.', exact: true }).waitFor();
  const progress = await json('/api/progress');
  assert.equal(progress.attempts, 3);
  assert.equal(progress.correct, 2);
  assert.equal(progress.hints_used, 4);
  assert.equal(progress.games_played, 0, 'Training must not fabricate played games');
  assert.equal(progress.topics.find((topic) => topic.topic === 'forks').attempts, 3);
  assert(progress.recommendations.length > 0);
  await assertStats({ 'Exercises tried': 3, 'Exercise accuracy': '67%', 'Hints used': 4 });
  await page.reload();
  await assertStats({ 'Exercises tried': 3, 'Exercise accuracy': '67%', 'Hints used': 4 });
  assert.equal((await json('/api/progress')).correct, 2);
  stages.push('three-ply reply/continuation, exact learning counts, and progress after reload');

  await page.getByRole('button', { name: 'Learn', exact: true }).click();
  await page.getByRole('tab', { name: 'Opening', exact: true }).click();
  for (const color of ['white', 'black']) {
    const name = `Deployment ${color} line`;
    await page.getByRole('button', { name: 'Add a line', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Add an opening line', exact: true });
    await dialog.getByLabel('Name', { exact: true }).fill(name);
    await dialog.getByLabel('Your color', { exact: true }).selectOption(color);
    await dialog.getByLabel('Moves from the starting position (SAN or UCI)', { exact: true }).fill('e4 e5 Nf3 Nc6 Bc4 Bc5');
    await dialog.getByRole('button', { name: 'Save preferences', exact: true }).click();
    const row = page.locator('.repertoire-line').filter({ hasText: name });
    await row.waitFor();
    const line = (await json('/api/repertoire')).find((entry) => entry.name === name);
    assert.equal(line.color, color);
    const pending = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/repertoire/${line.id}/practice` && response.request().method() === 'POST',
    );
    await row.getByRole('button', { name: 'Start practice', exact: true }).click();
    const response = await pending;
    assert.equal(response.status(), 200, await response.text());
    const practice = await response.json();
    assert(practice.exercises.length > 0);
    const exercise = practice.exercises[0];
    assert.equal(exercise.fen.split(' ')[1], color === 'white' ? 'w' : 'b');
    await page.getByRole('heading', { name: exercise.title, exact: true }).waitFor();
    const correct = await attempt(line.moves[color === 'white' ? 0 : 1], exercise.id);
    assert(correct.correct && correct.complete);
    await page.getByRole('heading', { name: 'Nicely spotted.', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Back to lessons', exact: true }).click();
  }
  assert.equal((await json('/api/repertoire')).length, 2);
  await page.reload();
  await assertStats({ 'Exercises tried': 5, 'Exercise accuracy': '80%', 'Hints used': 4 });
  stages.push('white and black repertoire creation, side-correct engine practice, and durable opening progress');

  await page.waitForFunction(() => 'serviceWorker' in navigator && navigator.serviceWorker.controller !== null, undefined, { timeout: 20000 });
  const privateRequests = await page.evaluate(async () => {
    const results = [];
    for (const path of ['/api/auth/me', '/api/progress', '/api/exercises', '/api/repertoire']) {
      const response = await fetch(path, { credentials: 'same-origin' });
      results.push({ path, status: response.status });
      await response.text();
    }
    return results;
  });
  assert(privateRequests.every((request) => request.status === 200));
  const cached = await page.evaluate(async () => {
    const paths = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) paths.push(new URL(request.url).pathname);
    }
    return paths;
  });
  assert(cached.some((path) => path.endsWith('.js')) && cached.some((path) => path.endsWith('.css')));
  assert(!cached.some((path) => path.startsWith('/api')), 'Authenticated API responses must never enter Cache Storage');
  await context.setOffline(true);
  await page.reload();
  await page.getByRole('heading', { name: 'Create account', exact: true }).waitFor();
  await context.setOffline(false);
  await page.reload();
  await page.getByRole('heading', { name: 'Play', exact: true }).waitFor();
  await assertStats({ 'Exercises tried': 5, 'Exercise accuracy': '80%', 'Hints used': 4 });
  stages.push('authenticated API cache exclusion, offline shell, and authenticated recovery');
  assert.deepEqual(errors, []);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await mkdir(directory, { recursive: true });
  const device = mobile ? 'mobile' : 'desktop';
  await page.screenshot({ path: `${directory}/training-${device}.png`, fullPage: true });
  const report = { baseURL, device, passed: stages, completedAt: new Date().toISOString() };
  await writeFile(`${directory}/training-${device}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  await mkdir(directory, { recursive: true });
  if (context?.pages()[0]) await context.pages()[0].screenshot({ path: `${directory}/training-failure.png`, fullPage: true }).catch(() => {});
  console.error('Completed stages before failure:', stages);
  throw error;
} finally {
  await browser.close();
}
