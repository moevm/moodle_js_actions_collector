import {test as base, expect} from '@playwright/test';
import {api} from './helpers.mjs';

export {expect};
export const test = base.extend({
  request: async ({playwright}, use) => {
    const anonymous = await playwright.request.newContext();
    let authenticated;
    try {
      const response = await anonymous.post(`${api}/auth/sign-in`, {data: {
        email: process.env.COLLECTOR_ADMIN_EMAIL, password: process.env.COLLECTOR_ADMIN_PASSWORD,
      }});
      expect(response.ok(), `Collector login: HTTP ${response.status()}`).toBeTruthy();
      const session = await response.json();
      expect(typeof session.access_token).toBe('string');
      authenticated = await playwright.request.newContext({
        extraHTTPHeaders: {Authorization: `Bearer ${session.access_token}`},
      });
      await use(authenticated);
    } finally {
      await authenticated?.dispose();
      await anonymous.dispose();
    }
  },
});
