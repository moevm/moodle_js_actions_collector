import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, demo, markedUrl} from './helpers.mjs';

const privateReads = ['/statistics/', '/download/statistics', '/download/sessions', '/user/', '/healthcheck/storage'];

test('auth: anonymous requests cannot read, export or delete collector data', async ({playwright}) => {
  const anonymous = await playwright.request.newContext();
  try {
    for (const path of privateReads) expect((await anonymous.get(api + path)).status()).toBe(401);
    expect((await anonymous.delete(`${api}/statistics/60d5ec49f1a4a21f6c8b4567`)).status()).toBe(401);
    expect((await anonymous.delete(`${api}/user/60d5ec49f1a4a21f6c8b4567`)).status()).toBe(401);
    expect((await anonymous.post(`${api}/statistics/page`, {data: {
      page: markedUrl(demo.reading), title: 'Unauthorized probe', browser: 'test', window: {width: 1, height: 1},
    }})).status()).toBe(401);
  } finally { await anonymous.dispose(); }
});

test('auth: the Moodle collection key permits no reading or management', async ({playwright}) => {
  expect(Boolean(process.env.COLLECTOR_INGEST_KEY), 'Collection key must be configured for E2E').toBe(true);
  const writer = await playwright.request.newContext({
    extraHTTPHeaders: {Authorization: `Bearer ${process.env.COLLECTOR_INGEST_KEY}`},
  });
  try {
    for (const path of privateReads) expect((await writer.get(api + path)).status()).toBe(401);
    expect((await writer.delete(`${api}/statistics/60d5ec49f1a4a21f6c8b4567`)).status()).toBe(401);
    expect((await writer.delete(`${api}/user/60d5ec49f1a4a21f6c8b4567`)).status()).toBe(401);
  } finally { await writer.dispose(); }
});

test('auth: login returns a password-free session and tampered tokens are rejected', async ({playwright}) => {
  const anonymous = await playwright.request.newContext();
  let tampered;
  try {
    const response = await anonymous.post(`${api}/auth/sign-in`, {data: {
      email: process.env.COLLECTOR_ADMIN_EMAIL, password: process.env.COLLECTOR_ADMIN_PASSWORD,
    }});
    expect(response.ok()).toBe(true);
    const session = await response.json();
    expect('password' in session).toBe(false);
    expect(typeof session.access_token).toBe('string');
    expect(response.headers()['cache-control']).toBe('no-store');
    tampered = await playwright.request.newContext({
      extraHTTPHeaders: {Authorization: `Bearer ${session.access_token}.corrupt`},
    });
    expect((await tampered.get(`${api}/statistics/`)).status()).toBe(401);
  } finally {
    await tampered?.dispose();
    await anonymous.dispose();
  }
});

test('auth: a regular collector user can read statistics but cannot manage data', async ({playwright, request}) => {
  const password = `Temporary!${randomUUID()}`;
  const created = await request.post(`${api}/user/`, {data: {
    email: `e2e-${randomUUID()}@example.com`, name: 'E2E', surname: 'Reader', lastname: 'Test', password,
  }});
  expect(created.status()).toBe(201);
  const user = await created.json();
  let reader;
  const anonymous = await playwright.request.newContext();
  try {
    expect('password' in user).toBe(false);
    const login = await anonymous.post(`${api}/auth/sign-in`, {data: {email: user.email, password}});
    expect(login.ok()).toBe(true);
    const session = await login.json();
    reader = await playwright.request.newContext({extraHTTPHeaders: {Authorization: `Bearer ${session.access_token}`}});
    expect((await reader.get(`${api}/statistics/`, {params: {student_id: 2147483647}})).status()).toBe(200);
    expect((await reader.get(`${api}/user/`)).status()).toBe(403);
    expect((await reader.delete(`${api}/statistics/60d5ec49f1a4a21f6c8b4567`)).status()).toBe(403);
  } finally {
    await reader?.dispose();
    await anonymous.dispose();
    expect((await request.delete(`${api}/user/${user.id}`)).status()).toBe(204);
  }
});
