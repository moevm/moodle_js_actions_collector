import {test, expect} from './fixtures.mjs';
import {randomUUID} from 'node:crypto';
import {api, demo, login, markedUrl} from './helpers.mjs';

function assignmentEditUrl() {
  const url = new URL(markedUrl(demo.assignment));
  url.searchParams.set('action', 'editsubmission');
  return url.href;
}

async function saveAssignment(page, text) {
  const fieldName = 'onlinetext_editor[text]';
  const textarea = page.locator(`textarea[name="${fieldName}"]`);
  // Moodle sets this marker after awaiting tinyMCE.init(). An editable iframe
  // can appear earlier, before the form-submit and blur handlers are installed.
  await expect(textarea, 'Moodle must finish setting up the TinyMCE form field')
    .toHaveAttribute('data-fieldtype', 'editor');
  const editor = page.frameLocator('iframe.tox-edit-area__iframe').locator('body');
  await expect(editor).toBeEditable();
  await editor.press('ControlOrMeta+a');
  await editor.pressSequentially(text);
  await expect(editor).toContainText(text);
  // Use the normal blur/save path; never call editor.save() or alter the hidden
  // textarea from the test, which could conceal a Moodle integration failure.
  await editor.press('Tab');
  await expect.poll(() => textarea.inputValue(), {
    message: 'TinyMCE must copy the typed answer to the Moodle form on blur',
  }).toContain(text);
  const [submission] = await Promise.all([
    page.waitForRequest(request => request.method() === 'POST'
      && new URL(request.url()).pathname === '/mod/assign/view.php'),
    page.locator('#id_submitbutton').click(),
  ]);
  // Moodle can submit multipart/form-data; parse the actual browser request
  // instead of treating a successful navigation as proof that the answer saved.
  const submitted = await new Request(submission.url(), {
    method: 'POST',
    headers: {'Content-Type': submission.headers()['content-type']},
    body: submission.postDataBuffer(),
  }).formData();
  expect(submitted.get(fieldName), 'The Moodle POST must contain the typed answer').toContain(text);
  await expect(page).toHaveURL(/\/mod\/assign\/view\.php/);
  await expect(page.locator('.submissionstatustable')).toContainText(text);
}

test('resilience: assignment saves while the collector API is unavailable', async ({page}) => {
  await login(page);
  let blocked = 0;
  await page.route(`${api}/statistics/**`, route => {
    blocked++;
    return route.abort('connectionfailed');
  });
  await page.goto(assignmentEditUrl(), {waitUntil: 'domcontentloaded'});
  await saveAssignment(page, `Saved with unavailable collector ${randomUUID()}`);
  await expect.poll(() => blocked).toBeGreaterThan(0);
});

test('resilience: assignment saves without waiting for a stalled collector request', async ({page}) => {
  await login(page);
  let blocked = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route(`${api}/statistics/**`, async route => {
    blocked++;
    await gate;
    // The old document may have cancelled its request after saving/navigating.
    // Teardown must not turn that expected cancellation into a test failure.
    await route.abort('connectionfailed').catch(() => {});
  });
  try {
    await page.goto(assignmentEditUrl(), {waitUntil: 'domcontentloaded'});
    await saveAssignment(page, `Saved with stalled collector ${randomUUID()}`);
    await expect.poll(() => blocked).toBeGreaterThan(0);
  } finally {
    release();
    await page.unrouteAll({behavior: 'wait'});
  }
});

test('resilience: a stalled tracker script does not gate DOMContentLoaded or form controls', async ({page}) => {
  await login(page);
  let blocked = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/local/actioncollector/collector.js*', async route => {
    blocked++;
    await gate;
    await route.abort('connectionfailed');
  });
  try {
    await page.goto(markedUrl(demo.playground), {waitUntil: 'domcontentloaded', timeout: 15000});
    await expect.poll(() => blocked).toBeGreaterThan(0);
    await page.locator('#collector-demo-answer').fill('The Moodle form still works');
    await expect(page.locator('#collector-demo-answer')).toHaveValue('The Moodle form still works');
    await page.locator('#collector-demo-checkbox').check();
    await expect(page.locator('#collector-demo-checkbox')).toBeChecked();
    await expect(page.locator('#collector-demo-button')).toBeEnabled();
  } finally {
    release();
    await page.unrouteAll({behavior: 'wait'});
  }
});
