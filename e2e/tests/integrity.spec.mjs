import {test, expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {demo, api, login, markedUrl, trackerReady, flush, identity,
  clipboardPermissions, selectText} from './helpers.mjs';

async function sessions(request, url) {
  const response = await request.get(`${api}/statistics/`, {params: {pageSize: -1}});
  expect(response.ok()).toBeTruthy();
  const [rows] = await response.json();
  return rows.filter(row => row.url === url);
}
const clicks = rows => rows.flatMap(row => row.actions)
  .filter(a => a.event_type === 'mousedown' && a.element_name === 'collector-demo-button');
async function open(page, url) {
  await page.goto(url);
  await trackerReady(page);
  await flush(page);
}
async function clickAndFlush(page) {
  await page.locator('#collector-demo-button').click();
  await flush(page);
}

test('integrity: two students keep separate identities on the same URL', async ({browser, request}) => {
  expect(Number(demo.student2_id), 'Run the updated Moodle seed before this suite').toBeGreaterThan(0);
  const first = await browser.newContext();
  const second = await browser.newContext();
  try {
    const a = await first.newPage();
    const b = await second.newPage();
    await login(a);
    await login(b, demo.playground, 'student2');
    const url = markedUrl(demo.playground);
    await open(a, url);
    await open(b, url);
    const identities = [await identity(a), await identity(b)];
    expect(identities.map(i => i.student_id)).toEqual([Number(demo.student_id), Number(demo.student2_id)]);
    await clickAndFlush(a);
    await clickAndFlush(b);
    const rows = await sessions(request, url);
    expect([...new Set(rows.map(r => r.student_id))].sort()).toEqual(
      [Number(demo.student_id), Number(demo.student2_id)].sort());
    for (const who of identities) {
      const own = rows.filter(r => r.student_id === who.student_id);
      expect(clicks(own)).toHaveLength(1);
      for (const row of own) {
        expect(row.email).toBe(who.email);
        expect(row.student).toBe(who.student);
        expect(row.course).toBe('Collector Demo Course');
      }
    }
  } finally {
    await first.close();
    await second.close();
  }
});

test('integrity: two independent tabs keep separate tab IDs on the same URL', async ({page, context, request}) => {
  await login(page);
  const other = await context.newPage();
  const url = markedUrl(demo.playground);
  await open(page, url);
  await open(other, url);
  await clickAndFlush(page);
  await clickAndFlush(other);
  const rows = await sessions(request, url);
  const ids = [...new Set(rows.map(r => r.tabID))];
  expect(ids).toHaveLength(2);
  for (const id of ids) {
    expect(id).toBeTruthy();
    const own = rows.filter(r => r.tabID === id);
    expect(clicks(own)).toHaveLength(1);
    expect(own.every(r => r.student_id === Number(demo.student_id))).toBe(true);
  }
});

test('integrity: repeated tracker loading and flushing do not duplicate one click', async ({page, request}) => {
  await login(page);
  const url = markedUrl(demo.playground);
  await open(page, url);
  // Execute the real script a second time, as can happen with duplicate inclusion.
  await page.addScriptTag({url: new URL('/local/actioncollector/collector.js', url).href});
  await clickAndFlush(page);
  await flush(page);
  const rows = await sessions(request, url);
  expect(clicks(rows)).toHaveLength(1);
  expect(rows.flatMap(r => r.actions).filter(a => a.event_type === 'open page')).toHaveLength(1);
});

test('integrity: field values and clipboard contents stay out of events and page snapshots', async ({page, context, request}) => {
  await clipboardPermissions(context);
  await login(page);
  const secret = `private-${randomUUID()}`;
  // Moodle renders these fixtures itself; do not intercept the document response.
  const target = new URL(markedUrl(demo.playground));
  target.searchParams.set('privacy_probe', secret.slice('private-'.length));
  const url = target.href;
  await open(page, url);
  await expect(page.locator('#privacy-text')).toHaveValue(secret);
  await page.locator('#privacy-password').click();
  await page.locator('#privacy-password').fill(secret + '-typed');
  await page.locator('#privacy-editor').click();
  await selectText(page, '#privacy-editor');
  await page.keyboard.press('Control+c');
  await page.locator('#collector-demo-answer').click();
  await page.keyboard.press('Control+v');
  await expect(page.locator('#collector-demo-answer')).toHaveValue(secret);
  await flush(page);
  const rows = await sessions(request, url);
  const actions = rows.flatMap(r => r.actions);
  expect(actions.some(a => a.event_type === 'copy')).toBe(true);
  expect(actions.some(a => a.event_type === 'paste')).toBe(true);
  expect(actions.some(a => a.element_name === 'privacy-password')).toBe(false);
  expect(JSON.stringify(rows).includes(secret)).toBe(false);
  const response = await request.get(`${api}/download/sessions`);
  expect(response.ok()).toBeTruthy();
  const snapshots = (await response.json()).filter(row => row.page === url);
  expect(snapshots).toHaveLength(1);
  expect(snapshots[0].page_html.includes('Public fixture marker'),
    'Saved snapshot must contain the fixture marker; otherwise privacy was not exercised').toBe(true);
  expect(JSON.stringify(snapshots).includes(secret)).toBe(false);
});

test('integrity: blocked delivery retains events and retries automatically without duplicates', async ({page, request}) => {
  await login(page);
  const url = markedUrl(demo.playground);
  await open(page, url);
  let blocked = 0;
  const endpoint = `${api}/statistics/`;
  const fail = async route => {
    blocked++;
    await route.abort('connectionfailed');
  };
  await page.route(endpoint, fail);
  try {
    for (let i = 0; i < 3; i++) await page.locator('#collector-demo-button').click();
    // Wait for the collector's own timer, without invoking flush ourselves.
    await expect.poll(() => blocked, {timeout: 15000}).toBeGreaterThan(0);
    await expect.poll(() => page.evaluate(() => window.actionCollector.error)).toBeTruthy();
    expect(await page.evaluate(() => window.actionCollector.queued)).toBeGreaterThanOrEqual(3);
    expect(clicks(await sessions(request, url))).toHaveLength(0);
  } finally {
    await page.unroute(endpoint, fail);
  }
  await expect.poll(() => page.evaluate(() => window.actionCollector.queued), {timeout: 15000}).toBe(0);
  expect(await page.evaluate(() => window.actionCollector.error)).toBeNull();
  expect(clicks(await sessions(request, url))).toHaveLength(3);
  // A subsequent successful delivery must not resend the recovered batch.
  await clickAndFlush(page);
  expect(clicks(await sessions(request, url))).toHaveLength(4);
});
