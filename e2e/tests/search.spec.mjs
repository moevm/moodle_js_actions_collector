import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, collector, demo, markedUrl} from './helpers.mjs';

test('search: literal field names agree in the API, export and actual table', async ({playwright, page, request}) => {
  const writer = await playwright.request.newContext({
    extraHTTPHeaders: {Authorization: `Bearer ${process.env.COLLECTOR_INGEST_KEY}`},
  });
  const ids = [];
  const email = `search-${randomUUID()}@example.com`;
  try {
    const url = markedUrl(demo.reading);
    const registration = await writer.post(`${api}/statistics/page`, {data: {
      page: url, title: 'Search probe', browser: 'E2E', window: {width: 1, height: 1},
    }});
    expect(registration.status()).toBe(201);
    const session_id = await registration.json();
    const event = (element_name, event_type = 'mousedown') => ({element_name, event_type,
      timestamp: new Date().toISOString(), element_type: 'input', action_type: 'conversation', element_html: '<input>'});
    for (const actions of [[event('answer[0]'), event('a+b')], [event('answer0')],
      [event('other'), event('answer[0]', 'keydown')]]) {
      const saved = await writer.post(`${api}/statistics/`, {data: {
        student_id: 2147483000, student: 'E2E search', email, course: 'E2E',
        tabID: randomUUID(), url, session_id, actions,
      }});
      expect(saved.status()).toBe(201);
      ids.push((await saved.json()).id);
    }
    const params = {student_email: email, element_name: 'answer[0]', event_type: 'mousedown'};
    const response = await request.get(`${api}/statistics/`, {params});
    expect(response.status()).toBe(200);
    const [rows, total] = await response.json();
    expect(total).toBe(1);
    expect(rows).toHaveLength(1);
    expect(rows[0].actions.map(action => action.element_name)).toEqual(['answer[0]']);
    const exported = await request.get(`${api}/download/statistics`, {params});
    expect(exported.status()).toBe(200);
    const [downloaded, count] = await exported.json();
    expect(count).toBe(total);
    expect(downloaded.map(row => row._id)).toEqual(rows.map(row => row._id));
    expect(downloaded[0].actions.map(action => action.element_name)).toEqual(['answer[0]']);

    await page.goto(`${collector}/e.moevm.statistics/auth`);
    await page.locator('#email-input').fill(process.env.COLLECTOR_ADMIN_EMAIL);
    await page.locator('#password-input').fill(process.env.COLLECTOR_ADMIN_PASSWORD);
    await page.locator('#sign-in-button').click();
    await expect(page).toHaveURL(/\/e\.moevm\.statistics\/statistics/);
    await page.locator('#search-email').fill(email);
    await page.locator('#search-element-name').fill('answer[0]');
    await page.locator('#search-event-type').fill('mousedown');
    const loaded = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/api/statistics/')
      && new URL(r.url()).searchParams.get('student_email') === email);
    await page.locator('#start-search').click();
    expect((await loaded).status()).toBe(200);
    await expect(page.locator('.custom-table tbody')).toContainText('answer[0]');
    await expect(page.locator('.custom-table tbody')).not.toContainText('answer0');
    await expect(page.locator('.custom-table tbody')).not.toContainText('a+b');
  } finally {
    await writer.dispose();
    for (const id of ids) expect((await request.delete(`${api}/statistics/${id}`)).status()).toBe(204);
  }
});
