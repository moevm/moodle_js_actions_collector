import {test, expect} from '@playwright/test';
import {
  demo, collector, markedUrl, login, trackerReady, flush, identity,
  actionsFor, expectEvents, selectText, clipboardPermissions,
} from './helpers.mjs';

test('login returns to the requested reading page and persists its opening', async ({page, request}) => {
  await login(page, demo.reading);
  const url = new URL(page.url());
  expect(url.pathname).toBe('/mod/page/view.php');
  expect(url.searchParams.get('id')).toBe(new URL(demo.reading).searchParams.get('id'));
  await expect(page.getByRole('heading', {name: 'Collector demo material'})).toBeVisible();
  const student = await identity(page);
  expect(student.student_id).toBeGreaterThan(0);
  expect(student.course).toBe('Collector Demo Course');
  // Reading login can canonicalize query parameters. Subsequent tests use unique
  // URLs to distinguish new test events from previously stored activity.
  await page.goto(markedUrl(demo.reading));
  await trackerReady(page);
  const current = await identity(page);
  await flush(page);
  await expectEvents(request, current, ['open page']);
});

test('real mouse, clipboard, scrolling and page exit reach the collector API', async ({page, context, request}) => {
  await clipboardPermissions(context);
  await login(page);
  await page.goto(markedUrl(demo.playground));
  await trackerReady(page);
  const student = await identity(page);
  await page.locator('#collector-demo-button').click();
  const source = await page.locator('#copy-source').innerText();
  await selectText(page, '#copy-source');
  await page.keyboard.press('Control+c');
  await page.locator('#collector-demo-answer').click();
  await page.keyboard.press('Control+v');
  await expect(page.locator('#collector-demo-answer')).toHaveValue(source);
  await page.locator('#copy-source').click({button: 'right'});
  await page.keyboard.press('Escape');
  await page.mouse.wheel(0, 1000);
  await expect.poll(() => page.evaluate(() => Math.max(
    window.scrollY, document.scrollingElement?.scrollTop || 0,
    document.querySelector('#page')?.scrollTop || 0,
  ))).toBeGreaterThan(0);
  await flush(page);
  await expectEvents(request, student, ['open page', 'mousedown', 'copy', 'paste', 'contextmenu', 'scroll']);
  const actions = await actionsFor(request, student);
  expect(JSON.stringify(actions)).not.toContain(source);
  await page.goto('about:blank');
  await expectEvents(request, student, ['close page']);
});

test('TinyMCE paste is persisted and the assignment answer is saved', async ({page, context, request}) => {
  await clipboardPermissions(context);
  await login(page);
  const source = await page.locator('#copy-source').innerText();
  await selectText(page, '#copy-source');
  await page.keyboard.press('Control+c');
  const edit = new URL(markedUrl(demo.assignment));
  edit.searchParams.set('action', 'editsubmission');
  await page.goto(edit.href);
  await trackerReady(page);
  const student = await identity(page);
  const editor = page.frameLocator('iframe.tox-edit-area__iframe').locator('body');
  await expect(editor).toBeVisible();
  await editor.fill('');
  // Wait for observed iframe binding using real clicks and persisted events,
  // rather than sleeping or injecting synthetic collector events.
  await expect.poll(async () => {
    await editor.click();
    await flush(page);
    const events = await actionsFor(request, student, {element_type: 'editor'});
    return events.some(event => event.event_type === 'mousedown');
  }, {message: 'Tracker binds the real TinyMCE iframe'}).toBe(true);
  await page.keyboard.press('Control+v');
  await expect(editor).toContainText(source);
  await flush(page);
  await expectEvents(request, student, ['paste'], {element_type: 'editor'});
  const events = await actionsFor(request, student, {element_type: 'editor'});
  expect(JSON.stringify(events)).not.toContain(source);
  await page.locator('#id_submitbutton').click();
  await expect(page).toHaveURL(/\/mod\/assign\/view\.php/);
  await expect(page.locator('.submissionstatustable')).toContainText('Submitted for grading');
  await expect(page.locator('.submissionstatustable')).toContainText(source);
});

test('the demo quiz starts, accepts 4 and completes with a correct answer', async ({page, request}) => {
  await login(page, demo.quiz);
  await page.getByRole('button', {name: /^(Attempt quiz|Re-attempt quiz|Continue your attempt)$/}).click();
  const start = page.getByRole('button', {name: 'Start attempt', exact: true});
  await Promise.race([
    page.waitForURL(/\/mod\/quiz\/attempt\.php/),
    start.waitFor({state: 'visible'}),
  ]);
  if (await start.isVisible()) await start.click();
  await expect(page).toHaveURL(/\/mod\/quiz\/attempt\.php/);
  await page.goto(markedUrl(page.url()));
  await trackerReady(page);
  const student = await identity(page);
  await page.locator('.que.shortanswer input[type="text"]').fill('4');
  await flush(page);
  await expectEvents(request, student, ['open page']);
  await page.locator('input[name="next"], button[name="next"]').click();
  await expect(page).toHaveURL(/\/mod\/quiz\/summary\.php/);
  await page.getByRole('button', {name: 'Submit all and finish', exact: true}).click();
  const confirm = page.locator('.modal.show, [role="dialog"]:visible').last()
    .getByRole('button', {name: 'Submit all and finish', exact: true});
  await Promise.race([
    page.waitForURL(/\/mod\/quiz\/review\.php/),
    confirm.waitFor({state: 'visible'}),
  ]);
  if (await confirm.isVisible()) await confirm.click();
  await expect(page).toHaveURL(/\/mod\/quiz\/review\.php/);
  await expect(page.locator('.que.shortanswer .state')).toHaveText('Correct');
});

test('collector login and table show newly delivered browser events', async ({page, request}) => {
  await login(page);
  await page.goto(markedUrl(demo.playground));
  await trackerReady(page);
  const student = await identity(page);
  await page.locator('#collector-demo-button').click();
  await flush(page);
  await expectEvents(request, student, ['mousedown']);

  await page.goto(`${collector}/e.moevm.statistics/auth`);
  await page.locator('#email-input').fill(process.env.COLLECTOR_ADMIN_EMAIL);
  await page.locator('#password-input').fill(process.env.COLLECTOR_ADMIN_PASSWORD);
  const signedIn = page.waitForResponse(response =>
    response.url().endsWith('/api/auth/sign-in') && response.request().method() === 'POST');
  await page.locator('#sign-in-button').click();
  expect((await signedIn).ok()).toBeTruthy();
  await expect(page).toHaveURL(/\/e\.moevm\.statistics\/statistics/);
  await page.locator('#search-id').fill(String(student.student_id));
  await page.locator('#search-course').fill(student.course);
  const refreshed = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith('/api/statistics/')
    && response.request().method() === 'GET'
    && new URL(response.url()).searchParams.get('student_id') === String(student.student_id));
  await page.locator('#search-id').press('Enter');
  const response = await refreshed;
  expect(response.ok()).toBeTruthy();
  const [rows] = await response.json();
  expect(rows.some(row => row.url === student.url)).toBeTruthy();
  await expect(page.locator('.custom-table tbody')).toContainText(student.url);
  await expect(page.locator('.custom-table tbody')).toContainText('mousedown');

});
