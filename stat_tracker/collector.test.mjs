import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {setImmediate} from 'node:timers/promises';
import vm from 'node:vm';

const script = await readFile(new URL('./collector.js', import.meta.url), 'utf8');
const pageId = '60d5ec49f1a4a21f6c8b4567';
const ok = () => ({ok: true, json: async () => ({})});
const settle = () => setImmediate();

class Clock {
  now = 1700000000000;
  tasks = new Map();
  nextId = 0;
  add(callback, delay, period = 0) {
    const id = ++this.nextId;
    this.tasks.set(id, {callback, at: this.now + delay, period});
    return id;
  }
  async advance(milliseconds) {
    const end = this.now + milliseconds;
    while (true) {
      const next = [...this.tasks.entries()].filter(([, task]) => task.at <= end)
        .sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      const [id, task] = next;
      this.now = task.at;
      if (task.period) task.at += task.period;
      else this.tasks.delete(id);
      task.callback();
      await settle();
    }
    this.now = end;
    await settle();
  }
}

// Startup/queue contract tests with a controlled clock and transport.
// These do not replace real Moodle/browser tests.
async function startTracker({deliver = ok, register, requireReady = true} = {}) {
  const clock = new Clock();
  const requests = [];
  const listeners = new Map();
  const windowListeners = new Map();
  const storage = new Map();
  const document = {
    readyState: 'complete', title: 'Reading', visibilityState: 'visible',
    get documentElement() { throw new Error('Registration must not copy page HTML'); },
    querySelectorAll: () => [],
    addEventListener: (name, callback) => listeners.set(name, callback),
  };
  class TestDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock.now])); }
    static now() { return clock.now; }
  }
  const math = Object.create(Math);
  math.random = () => 0;
  const sandbox = {
    actionCollectorConfig: {
      apiUrl: 'https://collector.example/api',
      user: {student_id: 7, student: 'Student', email: 'student@example.com', course: 'Course'},
    },
    document, location: {href: 'https://moodle.example/mod/page/view.php?id=7'},
    navigator: {userAgent: 'test browser'}, innerWidth: 1200, innerHeight: 800,
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    addEventListener: (name, callback) => windowListeners.set(name, callback),
    setInterval: (callback, delay) => clock.add(callback, delay, delay),
    setTimeout: (callback, delay) => clock.add(callback, delay),
    clearTimeout: id => clock.tasks.delete(id),
    Date: TestDate, Math: math, AbortController, TextEncoder,
    console: {info() {}, warn() {}},
    fetch: async (url, options) => {
      const request = {url, body: JSON.parse(options.body), bytes: Buffer.byteLength(options.body), at: clock.now};
      requests.push(request);
      if (url.endsWith('/statistics/page')) {
        return register ? register(request, options) : {ok: true, json: async () => pageId};
      }
      return deliver(request, options);
    },
  };
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  vm.runInContext(script, context);
  await settle();
  const state = sandbox.actionCollector;
  if (requireReady) {
    assert.equal(state.ready, true, state.error);
    await state.flush();
  }
  function click(id = 'submit-answer') {
    const button = {
      nodeType: 1, tagName: 'BUTTON', id, textContent: 'Save changes',
      getAttribute: () => null,
      closest: selector => selector.startsWith('input[type=') ? null : button,
    };
    listeners.get('mousedown')({target: button,
      preventDefault() { throw new Error('Collector must not cancel a Moodle action'); }});
  }
  function select(optionCount) {
    listeners.get('change')({target: {
      nodeType: 1, tagName: 'SELECT', id: 'choice', getAttribute: () => null,
      matches: selector => selector === 'select',
      options: Array.from({length: optionCount}, () => ({selected: true})),
    }});
  }
  return {sandbox, context, requests, listeners, windowListeners, clock, state, click, select,
    batches: () => requests.filter(request => request.url.endsWith('/statistics/'))};
}

test('registration sends metadata without reading or serializing page HTML', async () => {
  const {requests} = await startTracker();
  const registrations = requests.filter(request => request.url.endsWith('/statistics/page'));
  assert.equal(registrations.length, 1);
  assert.deepEqual(registrations[0].body, {
    page: 'https://moodle.example/mod/page/view.php?id=7', browser: 'test browser',
    title: 'Reading', window: {width: 1200, height: 800},
  });
});

test('open/click events retain page ID, identity and element metadata', async () => {
  const {clock, state, click, batches} = await startTracker();
  click();
  await clock.advance(1000);
  await state.flush();
  for (const {body} of batches()) {
    assert.equal(body.session_id, pageId);
    assert.equal(body.student_id, 7);
    assert.ok(body.tabID);
  }
  const actions = batches().flatMap(({body}) => body.actions);
  assert.equal(actions.filter(action => action.event_type === 'open page').length, 1);
  const clicks = actions.filter(action => action.event_type === 'mousedown');
  assert.equal(clicks.length, 1);
  assert.equal(clicks[0].element_name, 'submit-answer');
  assert.equal(clicks[0].element_html, '<button>');
});

test('repeated script loading does not register the same page twice', async () => {
  const {sandbox, context, requests, state} = await startTracker();
  vm.runInContext(script, context);
  await state.flush();
  assert.equal(sandbox.actionCollector, state);
  assert.equal(requests.filter(request => request.url.endsWith('/statistics/page')).length, 1);
});

test('a producer flood retains at most 500 events and counts discarded oldest events', async () => {
  const {clock, state, click, batches} = await startTracker();
  for (let i = 0; i < 1200; i++) click(`event-${i}`);
  assert.equal(state.queued, 500);
  assert.equal(state.dropped, 700);
  assert.ok(state.queuedBytes <= 256 * 1024);
  await clock.advance(1000);
  await state.flush();
  assert.equal(batches().at(-1).body.actions[0].element_name, 'event-700');
  assert.equal(state.queued, 480);
});

test('queue byte limit accounts for multibyte UTF-8 names', async () => {
  const {state, click} = await startTracker();
  for (let i = 0; i < 800; i++) click('界'.repeat(160));
  assert.ok(state.dropped > 0);
  assert.ok(state.queued < 500);
  assert.ok(state.queuedBytes <= 256 * 1024);
});

test('an oversized event is discarded before it can poison delivery', async () => {
  const {state, select} = await startTracker();
  select(40000);
  assert.equal(state.dropped, 1);
  assert.equal(state.queued, 0);
  assert.equal(state.queuedBytes, 0);
});

test('request bodies stay under 48 KiB even when individual events are large', async () => {
  const {clock, state, select, batches} = await startTracker();
  for (let i = 0; i < 5; i++) select(6000);
  await clock.advance(1000);
  await state.flush();
  assert.equal(batches().at(-1).body.actions.length, 1);
  assert.ok(batches().every(request => request.bytes <= 48 * 1024));
  assert.equal(state.dropped, 0);
});

test('ordinary delivery is limited to one request per second and 20 events per batch', async () => {
  const {clock, state, click, batches} = await startTracker();
  for (let i = 0; i < 80; i++) click(`event-${i}`);
  for (let i = 0; i < 5; i++) {
    await clock.advance(1000);
    for (let call = 0; call < 30; call++) await state.flush();
  }
  const sent = batches();
  for (let i = 1; i < sent.length; i++) assert.ok(sent[i].at - sent[i - 1].at >= 1000);
  assert.ok(sent.every(request => request.body.actions.length <= 20));
  assert.equal(state.queued, 0);
  assert.equal(state.sent, 81);
});

test('delivery failures back off, manual flush respects backoff, recovery clears the error', async () => {
  let blocked = false;
  const app = await startTracker({deliver: async () => {
    if (blocked) throw new Error('API unavailable');
    return ok();
  }});
  const {clock, state, click, batches} = app;
  blocked = true;
  click();
  await clock.advance(1000);
  await state.flush();
  assert.match(state.error, /API unavailable/);
  assert.equal(state.retryAt - clock.now, 2000);
  const attempts = batches().length;
  for (let i = 0; i < 50; i++) await state.flush();
  assert.equal(batches().length, attempts);
  await clock.advance(2000);
  await state.flush();
  assert.equal(state.retryAt - clock.now, 4000);
  blocked = false;
  await clock.advance(5000);
  assert.equal(state.error, null);
  assert.equal(state.retryAt, 0);
  assert.equal(state.queued, 0);
  assert.equal(state.dropped, 0);
});

test('repeated failures cap retry delay at 30 seconds', async () => {
  let blocked = false;
  const {clock, state, click, batches} = await startTracker({deliver: async () => {
    if (blocked) throw new Error('API unavailable');
    return ok();
  }});
  blocked = true;
  click();
  await clock.advance(180000);
  assert.ok(state.retryAt - clock.now <= 30000);
  assert.ok(batches().length <= 11, 'A failed API must not be polled every heartbeat');
  assert.equal(state.queued, 1);
});

test('overflow cannot remove the in-flight batch or delete newer events on acknowledgement', async () => {
  let acknowledge;
  const {clock, state, click, batches} = await startTracker({deliver: request => {
    if (request.body.actions[0].event_type === 'open page') return ok();
    return new Promise(resolve => { acknowledge = () => resolve(ok()); });
  }});
  for (let i = 0; i < 5; i++) click(`active-${i}`);
  await clock.advance(1000);
  const delivery = state.flush();
  for (let i = 0; i < 1000; i++) click(`new-${i}`);
  assert.equal(state.queued, 500);
  assert.equal(state.dropped, 505);
  acknowledge();
  await delivery;
  assert.equal(state.sent, 6);
  assert.equal(state.queued, 495);
  assert.deepEqual(batches()[1].body.actions.map(action => action.element_name),
    ['active-0', 'active-1', 'active-2', 'active-3', 'active-4']);
});

test('timed out delivery returns its batch to a bounded queue', async () => {
  const {clock, state, click} = await startTracker({deliver: (request, options) => {
    if (request.body.actions[0].event_type === 'open page') return ok();
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('request timed out')), {once: true});
    });
  }});
  click();
  await clock.advance(1000);
  const delivery = state.flush();
  for (let i = 0; i < 1000; i++) click(`pending-${i}`);
  await clock.advance(10000);
  await delivery;
  assert.match(state.error, /timed out/);
  assert.equal(state.queued, 500);
  assert.ok(state.queuedBytes <= 256 * 1024);
});

test('page exit gets one best-effort flush without waiting for the normal cadence', async () => {
  const {state, click, batches, windowListeners} = await startTracker();
  click();
  windowListeners.get('pagehide')();
  await settle();
  assert.ok(batches().at(-1).body.actions.some(action => action.event_type === 'close page'));
  assert.equal(state.queued, 0);
  const count = batches().length;
  windowListeners.get('pagehide')();
  await settle();
  assert.equal(batches().length, count);
});

test('page exit does not bypass failure backoff', async () => {
  let blocked = false;
  const {clock, state, click, batches, windowListeners} = await startTracker({deliver: async () => {
    if (blocked) throw new Error('API unavailable');
    return ok();
  }});
  blocked = true;
  click();
  await clock.advance(1000);
  await state.flush();
  const count = batches().length;
  windowListeners.get('pagehide')();
  await settle();
  assert.equal(batches().length, count);
});

test('unavailable registration stops after three attempts and does not bind controls', async () => {
  const {clock, state, requests, listeners} = await startTracker({requireReady: false,
    register: async () => { throw new Error('API unavailable'); }});
  await clock.advance(20000);
  assert.equal(requests.length, 3);
  assert.equal(state.ready, false);
  assert.equal(state.queued, 0);
  assert.equal(listeners.has('mousedown'), false);
});
