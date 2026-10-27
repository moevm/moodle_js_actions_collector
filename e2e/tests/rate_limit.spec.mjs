import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, collector, demo, markedUrl} from './helpers.mjs';

test('login limits: repeated failures return 429 while ingestion and health remain available', async ({playwright, page}) => {
  const anonymous = await playwright.request.newContext();
  const writer = await playwright.request.newContext({
    extraHTTPHeaders: {Authorization: `Bearer ${process.env.COLLECTOR_INGEST_KEY}`},
  });
  const email = `e2e-limit-${randomUUID()}@example.com`;
  const credentials = {email, password: 'not-a-real-password'};
  try {
    for (let index = 0; index < 5; index++) {
      const response = await anonymous.post(`${api}/auth/sign-in`, {data: credentials});
      expect(response.status()).toBe(401);
      expect(await response.json()).toEqual({detail: 'Invalid credentials'});
    }
    const blocked = await anonymous.post(`${api}/auth/sign-in`, {
      data: credentials, headers: {'X-Forwarded-For': '203.0.113.123'},
    });
    expect(blocked.status()).toBe(429);
    expect(Number(blocked.headers()['retry-after'])).toBeGreaterThan(0);
    expect(blocked.headers()['cache-control']).toBe('no-store');

    await page.goto(`${collector}/e.moevm.statistics/auth`);
    await page.locator('#email-input').fill(email);
    await page.locator('#password-input').fill(credentials.password);
    const [message] = await Promise.all([
      page.waitForEvent('dialog').then(async dialog => {
        const text = dialog.message();
        await dialog.accept();
        return text;
      }),
      page.locator('#sign-in-button').click(),
    ]);
    expect(message).toContain('Слишком много попыток входа');

    expect((await anonymous.get(`${api}/healthcheck/`)).status()).toBe(200);
    const registered = await writer.post(`${api}/statistics/page`, {data: {
      page: markedUrl(demo.reading), title: 'Login limit probe', browser: 'E2E',
      window: {width: 1, height: 1},
    }});
    expect(registered.status()).toBe(201);
  } finally {
    await writer.dispose();
    await anonymous.dispose();
  }
});
