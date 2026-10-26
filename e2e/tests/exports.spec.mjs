import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, demo, markedUrl} from './helpers.mjs';

test('export: table rejects unbounded pages and accepts the maximum page size', async ({request}) => {
  for (const pageSize of [-1, 0, 101, 1000000000]) {
    const response = await request.get(`${api}/statistics/`, {params: {pageSize}});
    expect(response.status(), `pageSize=${pageSize}`).toBe(422);
  }
  const response = await request.get(`${api}/statistics/`, {params: {pageSize: 100}});
  expect(response.ok()).toBe(true);
  const [rows] = await response.json();
  expect(rows.length).toBeLessThanOrEqual(100);
});

test('export: JSON contains all matching batches regardless of the table page', async ({playwright, request}) => {
  const writer = await playwright.request.newContext({
    extraHTTPHeaders: {Authorization: `Bearer ${process.env.COLLECTOR_INGEST_KEY}`},
  });
  const ids = [];
  try {
    const url = markedUrl(demo.reading);
    const registration = await writer.post(`${api}/statistics/page`, {data: {
      page: url, browser: 'E2E export probe', title: 'Export probe', window: {width: 1, height: 1},
    }});
    expect(registration.status()).toBe(201);
    const session_id = await registration.json();
    const email = `export-${randomUUID()}@example.com`;
    for (let index = 0; index < 3; index++) {
      const response = await writer.post(`${api}/statistics/`, {data: {
        student_id: 2147483000, student: 'E2E export probe', email, course: 'E2E',
        tabID: `export-${index}`, url, session_id, actions: [],
      }});
      expect(response.status()).toBe(201);
      ids.push((await response.json()).id);
    }
    const page = await request.get(`${api}/statistics/`, {params: {student_email: email, pageSize: 1}});
    expect(page.status()).toBe(200);
    const [visible, total] = await page.json();
    expect(visible).toHaveLength(1);
    expect(total).toBe(3);
    const response = await request.get(`${api}/download/statistics`, {
      params: {student_email: email, page: 999, pageSize: 1},
    });
    expect(response.status()).toBe(200);
    expect(response.headers()['cache-control']).toBe('no-store');
    const [rows, exported] = await response.json();
    expect(exported).toBe(3);
    expect(rows).toHaveLength(3);
    expect(rows.every(row => row.email === email && row.url === url)).toBe(true);
  } finally {
    await writer.dispose();
    for (const id of ids) {
      expect((await request.delete(`${api}/statistics/${id}`)).status()).toBe(204);
    }
  }
});
