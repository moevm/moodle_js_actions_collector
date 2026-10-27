import {randomUUID} from 'node:crypto';
import {test, expect} from './fixtures.mjs';
import {api, collector} from './helpers.mjs';

test('users: concurrent duplicate creation and conflicting update return 409; UI keeps input', async ({request, page}) => {
  const ids = [];
  const email = `users-${randomUUID()}@example.com`;
  const password = `Temporary!${randomUUID()}`;
  const fields = {name: 'E2E', surname: 'User', lastname: 'Test', email, password};
  try {
    const outcomes = await Promise.all([
      request.post(`${api}/user/`, {data: fields}),
      request.post(`${api}/user/`, {data: fields}),
    ]);
    for (const response of outcomes) {
      if (response.status() === 201) ids.push((await response.json()).id);
    }
    expect(outcomes.map(response => response.status()).sort()).toEqual([201, 409]);
    const conflict = outcomes.find(response => response.status() === 409);
    expect((await conflict.json()).detail.code).toBe('email_conflict');

    const otherEmail = `users-other-${randomUUID()}@example.com`;
    const created = await request.post(`${api}/user/`, {data: {...fields, email: otherEmail}});
    expect(created.status()).toBe(201);
    const other = await created.json();
    ids.push(other.id);
    const update = await request.put(`${api}/user/${other.id}`, {data: {...fields, position: 'regular'}});
    expect(update.status()).toBe(409);
    expect((await update.json()).detail.code).toBe('email_conflict');
    const unchanged = await request.get(`${api}/user/${other.id}`);
    expect((await unchanged.json()).email).toBe(otherEmail);
    const selfEmail = await request.put(`${api}/user/${other.id}`, {
      data: {...fields, email: otherEmail, position: 'regular'},
    });
    expect(selfEmail.status()).toBe(200);

    await page.goto(`${collector}/e.moevm.statistics/auth`);
    await page.locator('#email-input').fill(process.env.COLLECTOR_ADMIN_EMAIL);
    await page.locator('#password-input').fill(process.env.COLLECTOR_ADMIN_PASSWORD);
    await page.locator('#sign-in-button').click();
    await expect(page).toHaveURL(/\/e\.moevm\.statistics\/statistics/);
    await page.goto(`${collector}/e.moevm.statistics/user`);
    await page.locator('#email-input').fill(email);
    await page.locator('#surname-input').fill(fields.surname);
    await page.locator('#name-input').fill(fields.name);
    await page.locator('#lastname-input').fill(fields.lastname);
    await page.locator('#password-input').fill(password);
    const rejected = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/user/');
    await page.locator('#create-button').click();
    expect((await rejected).status()).toBe(409);
    await expect(page.getByRole('alert')).toContainText('уже существует');
    await expect(page.locator('#email-input')).toHaveValue(email);
    await expect(page.locator('#name-input')).toHaveValue(fields.name);
    // Compare a boolean to avoid printing the temporary password on failure.
    expect(await page.locator('#password-input').inputValue() === password).toBe(true);
  } finally {
    for (const id of ids) expect((await request.delete(`${api}/user/${id}`)).status()).toBe(204);
  }
});
