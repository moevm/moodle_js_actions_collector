import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {setImmediate} from 'node:timers/promises';
import vm from 'node:vm';

const script = await readFile(new URL('./collector.js', import.meta.url), 'utf8');
const pageId = '60d5ec49f1a4a21f6c8b4567';

// This is a startup contract test, not a replacement for real-browser E2E.
// Accessing the DOM root fails deliberately: registration must not copy HTML.
async function startTracker() {
  const requests = [];
  const listeners = new Map();
  const storage = new Map();
  const document = {
    readyState: 'complete',
    title: 'Reading',
    get documentElement() { throw new Error('Page HTML must not be inspected for registration'); },
    querySelectorAll: () => [],
    addEventListener: (name, callback) => listeners.set(name, callback),
  };
  const sandbox = {
    actionCollectorConfig: {
      apiUrl: 'https://collector.example/api',
      user: {student_id: 7, student: 'Student', email: 'student@example.com', course: 'Course'},
    },
    document,
    location: {href: 'https://moodle.example/mod/page/view.php?id=7'},
    navigator: {userAgent: 'test browser'},
    innerWidth: 1200,
    innerHeight: 800,
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    addEventListener() {},
    setInterval() {},
    setTimeout() { return 0; },
    clearTimeout() {},
    AbortController,
    console: {info() {}, warn() {}},
    fetch: async (url, options) => {
      requests.push({url, body: JSON.parse(options.body)});
      return {ok: true, json: async () => url.endsWith('/statistics/page') ? pageId : {}};
    },
  };
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  vm.runInContext(script, context);
  await setImmediate();
  assert.equal(sandbox.actionCollector.ready, true, sandbox.actionCollector.error);
  await sandbox.actionCollector.flush();
  return {sandbox, context, requests, listeners};
}

test('page registration sends metadata without reading or serializing page HTML', async () => {
  const {requests} = await startTracker();
  const registrations = requests.filter(request => request.url.endsWith('/statistics/page'));
  assert.equal(registrations.length, 1);
  assert.deepEqual(registrations[0].body, {
    page: 'https://moodle.example/mod/page/view.php?id=7',
    browser: 'test browser',
    title: 'Reading',
    window: {width: 1200, height: 800},
  });
});

test('open and click events keep the page ID, identity and element metadata', async () => {
  const {sandbox, requests, listeners} = await startTracker();
  const button = {
    nodeType: 1,
    tagName: 'BUTTON',
    id: 'submit-answer',
    textContent: 'Save changes',
    getAttribute: () => null,
    closest: selector => selector.startsWith('input[type=') ? null : button,
  };
  listeners.get('mousedown')({target: button});
  await sandbox.actionCollector.flush();
  const batches = requests.filter(request => request.url.endsWith('/statistics/'));
  assert.ok(batches.length > 0);
  for (const {body} of batches) {
    assert.equal(body.session_id, pageId);
    assert.equal(body.student_id, 7);
    assert.ok(body.tabID);
    assert.equal(body.url, sandbox.location.href);
  }
  const actions = batches.flatMap(({body}) => body.actions);
  assert.equal(actions.filter(action => action.event_type === 'open page').length, 1);
  const clicks = actions.filter(action => action.event_type === 'mousedown');
  assert.equal(clicks.length, 1);
  assert.equal(clicks[0].element_name, 'submit-answer');
  assert.equal(clicks[0].element_html, '<button>');
});

test('loading the tracker again does not register the same page twice', async () => {
  const {sandbox, context, requests} = await startTracker();
  vm.runInContext(script, context);
  await sandbox.actionCollector.flush();
  assert.equal(requests.filter(request => request.url.endsWith('/statistics/page')).length, 1);
});
