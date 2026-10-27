import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, demo, markedUrl} from './helpers.mjs';

test('validation: malformed IDs and query parameters return 422; unknown valid IDs return 404', async ({request}) => {
  const update = {name: 'Probe', surname: 'User', lastname: 'Test', email: 'probe@example.com', position: 'regular'};
  for (const id of ['not-an-object-id', 'g'.repeat(24), '0'.repeat(23), '0'.repeat(25)]) {
    for (const resource of ['statistics', 'user']) {
      expect((await request.get(`${api}/${resource}/${id}`)).status()).toBe(422);
      expect((await request.delete(`${api}/${resource}/${id}`)).status()).toBe(422);
    }
    expect((await request.put(`${api}/user/${id}`, {data: update})).status()).toBe(422);
  }
  for (const params of [{page: 0}, {page: '999999999999999999999999'}, {pageSize: 0},
    {pageSize: -1}, {pageSize: 101}, {student_id: -1}, {student_id: '9223372036854775808'},
    {begin_timestamp: '2026-10-28T00:00:00Z', end_timestamp: '2026-10-27T00:00:00Z'},
    {begin_timestamp: '0001-01-01T00:00:00+14:00'}]) {
    expect((await request.get(`${api}/statistics/`, {params})).status()).toBe(422);
  }
  for (const params of [{student_id: '9223372036854775808'},
    {begin_timestamp: '2026-10-28T00:00:00Z', end_timestamp: '2026-10-27T00:00:00Z'}]) {
    expect((await request.get(`${api}/download/statistics`, {params})).status()).toBe(422);
  }
  for (const resource of ['statistics', 'user']) {
    // A future/all-FF ObjectId is well-formed, unlike the malformed IDs above.
    expect((await request.get(`${api}/${resource}/${'F'.repeat(24)}`)).status()).toBe(404);
  }
});

test('validation: invalid event bodies are rejected and a valid batch is still saved', async ({playwright, request}) => {
  const writer = await playwright.request.newContext({
    extraHTTPHeaders: {Authorization: `Bearer ${process.env.COLLECTOR_INGEST_KEY}`},
  });
  const ids = [];
  try {
    const url = markedUrl(demo.reading);
    const registered = await writer.post(`${api}/statistics/page`, {data: {
      page: url, title: 'Validation probe', browser: 'E2E', window: {width: 1, height: 1},
    }});
    expect(registered.status()).toBe(201);
    const session_id = await registered.json();
    const event = {element_type: 'button', element_name: 'save', action_type: 'interactions',
      event_type: 'mousedown', element_html: '<button>'};
    const body = {student_id: 2147483001, student: 'E2E validation', email: `validation-${randomUUID()}@example.com`,
      course: 'E2E', tabID: randomUUID(), url, session_id,
      actions: [{...event, timestamp: '2026-10-27T10:00:00+03:00'}, {...event}]};
    for (const invalid of [
      {...body, session_id: randomUUID()},
      {...body, student_id: -1},
      {...body, student_id: 1e30},
      {...body, actions: [{...event, timestamp: '9999-12-31T23:59:59-12:00'}]},
    ]) {
      expect((await writer.post(`${api}/statistics/`, {data: invalid})).status()).toBe(422);
    }
    const saved = await writer.post(`${api}/statistics/`, {data: body});
    expect(saved.status()).toBe(201);
    const result = await saved.json();
    ids.push(result.id);
    const read = await request.get(`${api}/statistics/${result.id}`);
    expect(read.status()).toBe(200);
    const stored = await read.json();
    expect(stored.session_id).toBe(session_id);
    expect(stored.actions).toHaveLength(2);
    expect(stored.actions[0].timestamp).toMatch(/^2026-10-27T07:00:00/);
    expect(Number.isFinite(Date.parse(stored.actions[1].timestamp))).toBe(true);
  } finally {
    await writer.dispose();
    for (const id of ids) expect((await request.delete(`${api}/statistics/${id}`)).status()).toBe(204);
  }
});
