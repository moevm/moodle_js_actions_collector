import {expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';

export const demo = JSON.parse(readFileSync('artifacts/demo.json', 'utf8'));
export const collector = process.env.COLLECTOR_URL;
export const api = process.env.COLLECTOR_API_URL.replace(/\/$/, '');

export function markedUrl(value) {
  const url = new URL(value);
  url.searchParams.set('e2e_run', randomUUID());
  url.searchParams.set('lang', 'en');
  return url.href;
}

export async function login(page, target = demo.playground) {
  const response = await page.goto(markedUrl(target));
  if (!response?.ok()) {
    throw new Error(`Moodle page returned HTTP ${response?.status()}: ${page.url()}\n${(await page.locator('body').innerText()).slice(0, 2000)}`);
  }
  const body = await page.locator('body').innerText();
  if (/Fatal error:|Failed opening required/.test(body)) {
    throw new Error(`Moodle PHP error at ${page.url()}: ${body.slice(0, 2000)}`);
  }
  await expect(page.locator('#username')).toBeVisible();
  // Moodle core/togglesensitive replaces the password input asynchronously.
  // Wait for the replacement before filling: outerHTML loses a typed value.
  await expect(page.locator('#login .login-form-password .toggle-sensitive-btn'),
    'Moodle must finish replacing the password field before login').toHaveCount(1);
  await page.locator('#username').fill('student');
  await page.locator('#password').fill(process.env.MOODLE_STUDENT_PASSWORD);
  const [loginRequest] = await Promise.all([
    page.waitForRequest(request => request.method() === 'POST'
      && new URL(request.url()).pathname === '/login/index.php'),
    page.locator('#loginbtn').click(),
  ]);
  const submitted = new URLSearchParams(loginRequest.postData() ?? '');
  // Compare booleans so an assertion failure never prints the password.
  expect(submitted.get('password') === process.env.MOODLE_STUDENT_PASSWORD,
    'The login form must send the configured password without losing its value').toBe(true);
  await expect.poll(async () => {
    if (new URL(page.url()).pathname !== '/login/index.php') return true;
    const errors = await page.locator('#loginerrormessage').allTextContents();
    const message = errors.map(value => value.trim()).filter(Boolean).join(' ');
    if (message) {
      throw new Error(`Moodle rejected student login after the form sent the configured password: ${message}`);
    }
    return !/\/login\/index\.php/.test(new URL(page.url()).pathname);
  }, {message: 'Student login must succeed'}).toBe(true);
  await expect(page).not.toHaveURL(/\/login\/index\.php/);
  await trackerReady(page);
}

export async function trackerReady(page) {
  await expect.poll(() => page.evaluate(() => Boolean(window.actionCollector?.ready)), {
    message: 'Moodle plugin must start the real browser tracker',
  }).toBe(true);
  await expect(page.locator('.errorbox:visible, .alert-danger:visible')).toHaveCount(0);
}

export async function flush(page) {
  await page.evaluate(() => window.actionCollector.flush());
  await expect.poll(() => page.evaluate(() => window.actionCollector.error)).toBeNull();
  await expect.poll(() => page.evaluate(() => window.actionCollector.queued)).toBe(0);
}

export async function identity(page) {
  return page.evaluate(() => ({url: window.location.href, ...window.actionCollectorConfig.user}));
}

export async function actionsFor(request, student, filter = {}) {
  const response = await request.get(`${api}/statistics/`, {
    params: {student_id: student.student_id, pageSize: -1, ...filter},
  });
  expect(response.ok(), `Statistics API: HTTP ${response.status()}`).toBeTruthy();
  const [sessions] = await response.json();
  expect(Array.isArray(sessions)).toBeTruthy();
  return sessions.filter(session => session.url === student.url)
    .flatMap(session => {
      expect(session.email).toBe(student.email);
      expect(session.course).toBe(student.course);
      return session.actions;
    });
}

export async function expectEvents(request, student, events, filter = {}) {
  await expect.poll(async () => {
    const actions = await actionsFor(request, student, filter);
    const received = new Set(actions.map(action => action.event_type));
    return events.filter(event => !received.has(event));
  }, {message: `Persisted events: ${events.join(', ')}`, timeout: 20000}).toEqual([]);
}

export async function selectText(page, selector) {
  await page.locator(selector).evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  });
}

export async function clipboardPermissions(context) {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], {
    origin: new URL(process.env.MOODLE_URL).origin,
  });
}
