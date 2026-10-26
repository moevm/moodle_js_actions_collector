import {test, expect} from './fixtures.mjs';
import {randomUUID} from 'node:crypto';
import {demo, api, login, markedUrl, trackerReady, flush, identity, actionsFor} from './helpers.mjs';

async function setup(page) {
  await login(page);
  await page.goto(markedUrl(demo.playground));
  await trackerReady(page);
  await flush(page);
  return identity(page);
}

test('interactions: saved page records the real browser user agent', async ({page, request}) => {
  const who = await setup(page);
  const response = await request.get(`${api}/download/sessions`);
  expect(response.ok()).toBeTruthy();
  const rows = (await response.json()).filter(row => row.page === who.url);
  expect(rows).toHaveLength(1);
  const browser = rows[0].browser;
  expect(typeof browser).toBe('string');
  expect(browser.length).toBeGreaterThan(0);
  expect(browser).toBe(await page.evaluate(() => navigator.userAgent));
  expect(browser).toContain('Chrome/'); // This suite explicitly runs Chromium.
});

test('interactions: page registration sends only metadata and keeps events linked', async ({page, request}) => {
  const registrations = [];
  page.on('request', outgoing => {
    if (outgoing.method() === 'POST' && outgoing.url() === `${api}/statistics/page`) {
      registrations.push(outgoing.postDataJSON());
    }
  });
  const who = await setup(page);
  const sent = registrations.filter(body => body.page === who.url);
  expect(sent).toHaveLength(1);
  expect(Object.keys(sent[0]).sort()).toEqual(['browser', 'page', 'title', 'window']);
  expect(sent[0]).not.toHaveProperty('page_html');
  expect(sent[0].title).toBe(await page.title());
  expect(sent[0].browser).toBe(await page.evaluate(() => navigator.userAgent));
  expect(sent[0].window).toEqual(await page.evaluate(() => ({width: innerWidth, height: innerHeight})));

  const response = await request.get(`${api}/download/sessions`);
  expect(response.ok()).toBeTruthy();
  const pages = (await response.json()).filter(row => row.page === who.url);
  expect(pages).toHaveLength(1);
  expect(pages[0]).not.toHaveProperty('page_html');
  expect(pages[0]).toMatchObject(sent[0]);

  const eventsResponse = await request.get(`${api}/statistics/`, {params: {student_id: who.student_id, pageSize: -1}});
  expect(eventsResponse.ok()).toBeTruthy();
  const [batches] = await eventsResponse.json();
  const own = batches.filter(row => row.url === who.url);
  expect(own.length).toBeGreaterThan(0);
  expect(own.every(row => row.session_id === pages[0]._id)).toBe(true);
  expect(own.flatMap(row => row.actions).some(action => action.event_type === 'open page')).toBe(true);
});

test('interactions: real keyboard typing and deletion emit metadata without contents', async ({page, request}) => {
  const who = await setup(page);
  const secret = `answer-${randomUUID()}`;
  const answer = page.locator('#collector-demo-answer');
  await answer.click();
  await answer.pressSequentially(secret);
  await answer.press('Backspace');
  await expect(answer).toHaveValue(secret.slice(0, -1));
  await flush(page);
  const actions = await actionsFor(request, who);
  const keys = actions.filter(a => a.event_type === 'keydown' && a.element_name === 'demo-answer');
  expect(keys.filter(a => a.details?.keyboard_action === 'typing')).toHaveLength(secret.length);
  expect(keys.filter(a => a.details?.keyboard_action === 'editing')).toHaveLength(1);
  expect(JSON.stringify(actions).includes(secret)).toBe(false);
  for (const event of keys) {
    expect(event.element_html).toBe('<textarea>');
    expect(event.details).not.toHaveProperty('key');
    expect(event.details).not.toHaveProperty('value');
  }
});

test('interactions: checkbox records both checked and unchecked states once', async ({page, request}) => {
  const who = await setup(page);
  const checkbox = page.locator('#collector-demo-checkbox');
  await checkbox.check();
  await expect(checkbox).toBeChecked();
  await checkbox.uncheck();
  await expect(checkbox).not.toBeChecked();
  await flush(page);
  const changes = (await actionsFor(request, who)).filter(a =>
    a.event_type === 'change' && a.element_name === 'demo-checkbox');
  expect(changes).toHaveLength(2);
  expect(changes.map(a => a.details?.checked)).toEqual([true, false]);
  expect(changes.every(a => a.element_type === 'checkbox')).toBe(true);
});

test('interactions: select records chosen indices including reset without option values', async ({page, request}) => {
  const who = await setup(page);
  const select = page.locator('#collector-demo-select');
  await select.selectOption('beta');
  await expect(select).toHaveValue('beta');
  await select.selectOption('alpha');
  await expect(select).toHaveValue('alpha');
  await select.selectOption('');
  await expect(select).toHaveValue('');
  await flush(page);
  const changes = (await actionsFor(request, who)).filter(a =>
    a.event_type === 'change' && a.element_name === 'demo-select');
  expect(changes).toHaveLength(3);
  expect(changes.map(a => a.details?.selected_indices)).toEqual([[2], [1], [0]]);
  for (const change of changes) {
    expect(change.element_type).toBe('select');
    expect(change.details.option_count).toBe(3);
    expect(change.details).not.toHaveProperty('value');
    expect(change.details).not.toHaveProperty('label');
  }
});
