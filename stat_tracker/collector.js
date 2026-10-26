/* Shared browser tracker. Configuration is supplied by the Moodle adapter. */
(() => {
  'use strict';
  const config = window.actionCollectorConfig;
  if (!config || window.actionCollector || !config.user) return;
  const api = config.apiUrl.replace(/\/$/, '');
  const MAX_QUEUE_EVENTS = 500;
  const MAX_QUEUE_BYTES = 256 * 1024;
  const MAX_BATCH_EVENTS = 20;
  const MAX_BATCH_BYTES = 48 * 1024;
  const MIN_SEND_INTERVAL = 1000;
  const MAX_RETRY_DELAY = 30000;
  const encoder = new TextEncoder();
  const state = {ready: false, queued: 0, queuedBytes: 0, sent: 0, dropped: 0, retryAt: 0, error: null};
  window.actionCollector = state;
  if (typeof config.ingestKey !== 'string' || !config.ingestKey) {
    state.error = 'Collection key is not configured';
    return;
  }
  let queue = [];
  let queueBytes = 0;
  let active = [];
  let activeBytes = 0;
  let base;
  let baseBytes = 0;
  let flight;
  let nextSendAt = 0;
  let failures = 0;
  let closing = false;
  const documents = new WeakSet();

  async function post(path, body, keepalive = false) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(api + path, {
        method: 'POST', credentials: 'omit',
        headers: {'Content-Type': 'application/json', Authorization: `Bearer ${config.ingestKey}`},
        body: JSON.stringify(body), keepalive, signal: controller.signal
      });
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timer); }
  }

  function syncQueueState() {
    state.queued = queue.length + active.length;
    state.queuedBytes = queueBytes + activeBytes;
  }

  function trimQueue() {
    // Never remove a batch that is already in flight. Older pending events
    // are expendable: telemetry must not consume unbounded student memory.
    while (queue.length && (queue.length + active.length > MAX_QUEUE_EVENTS
        || queueBytes + activeBytes > MAX_QUEUE_BYTES)) {
      queueBytes -= queue.shift().bytes;
      state.dropped++;
    }
    syncQueueState();
  }

  function flush(final = false) {
    if (flight) return flight;
    if (!base || !queue.length) return Promise.resolve();
    const now = Date.now();
    // A page exit may bypass the normal cadence once, but not failure backoff.
    if (now < state.retryAt || (!final && now < nextSendAt)) return Promise.resolve();
    let bodyBytes = baseBytes;
    let count = 0;
    while (count < queue.length && count < MAX_BATCH_EVENTS) {
      const extra = queue[count].bytes + (count ? 1 : 0);
      if (bodyBytes + extra > MAX_BATCH_BYTES) break;
      bodyBytes += extra;
      count++;
    }
    if (!count) return Promise.resolve();
    active = queue.splice(0, count);
    activeBytes = active.reduce((total, entry) => total + entry.bytes, 0);
    queueBytes -= activeBytes;
    syncQueueState();
    nextSendAt = now + MIN_SEND_INTERVAL;
    flight = (async () => {
      await post('/statistics/', {...base, actions: active.map(entry => entry.action)}, true);
      state.sent += active.length;
      active = [];
      activeBytes = 0;
      failures = 0;
      state.retryAt = 0;
      state.error = null;
    })().catch(error => {
      queue = active.concat(queue);
      queueBytes += activeBytes;
      active = [];
      activeBytes = 0;
      trimQueue();
      failures = Math.min(failures + 1, 5);
      const delay = Math.min(MAX_RETRY_DELAY, 2000 * 2 ** (failures - 1));
      state.retryAt = Date.now() + Math.min(MAX_RETRY_DELAY, delay + Math.floor(Math.random() * delay * 0.25));
      state.error = String(error);
      console.warn('[collector] delivery failed', error);
    }).finally(() => { syncQueueState(); flight = null; });
    return flight;
  }
  state.flush = () => flush();

  function record(action, event, type = 'page', name = 'page', details) {
    const entry = {
      timestamp: new Date().toISOString(), action_type: action, event_type: event,
      element_type: type, element_name: String(name).slice(0, 160),
      // Do not transmit field contents, passwords or clipboard text.
      element_html: type === 'page' ? '' : '<' + type + '>',
      ...(details ? {details} : {})
    };
    const bytes = encoder.encode(JSON.stringify(entry)).byteLength;
    if (baseBytes + bytes > MAX_BATCH_BYTES) {
      state.dropped++;
      return;
    }
    queue.push({action: entry, bytes});
    queueBytes += bytes;
    trimQueue();
    if (queue.length >= 5) void flush();
  }

  function bindDocument(doc, editor = false) {
    if (documents.has(doc)) return;
    documents.add(doc);
    for (const eventName of ['mousedown', 'copy', 'paste', 'contextmenu']) {
      doc.addEventListener(eventName, event => {
        const target = event.target;
        if (!target || target.nodeType !== 1 || target.closest('input[type="password"]')) return;
        const element = target.closest('a,button,input,textarea,[contenteditable="true"]') || target;
        const type = editor ? 'editor' : element.tagName.toLowerCase();
        const name = editor ? 'answer-editor' : (element.getAttribute('aria-label')
          || element.getAttribute('name') || element.id
          || (['a', 'button'].includes(type) ? element.textContent.trim() : type));
        record('interactions', eventName, type, name);
      }, {capture: true});
    }
    doc.addEventListener('change', event => {
      const element = event.target;
      if (!element || element.nodeType !== 1) return;
      const name = element.getAttribute('name') || element.id || element.tagName.toLowerCase();
      if (element.matches('input[type="checkbox"]')) {
        record('interactions', 'change', 'checkbox', name, {checked: element.checked});
      } else if (element.matches('select')) {
        // Indices describe the choice without transmitting answer text or values.
        const selected = Array.from(element.options).flatMap((option, index) => option.selected ? [index] : []);
        record('interactions', 'change', 'select', name, {
          selected_indices: selected, option_count: element.options.length
        });
      }
    }, {capture: true});
    let lastScroll = 0;
    doc.addEventListener('scroll', () => {
      if (Date.now() - lastScroll < 1000) return;
      lastScroll = Date.now();
      record('conversation', 'scroll', editor ? 'editor' : 'page');
    }, {capture: true, passive: true});
    doc.addEventListener('keydown', event => {
      const element = event.target;
      const editable = element?.nodeType === 1 && (element.isContentEditable
        || element.matches('textarea,input:not([type]),input[type="text"],input[type="search"],input[type="email"],input[type="url"],input[type="tel"],input[type="number"]'));
      if (editable && !event.ctrlKey && !event.metaKey && !event.altKey
          && (event.key.length === 1 || ['Backspace', 'Delete', 'Enter'].includes(event.key))) {
        const type = editor ? 'editor' : element.tagName.toLowerCase();
        const name = editor ? 'answer-editor' : (element.getAttribute('name') || element.id || type);
        record('interactions', 'keydown', type, name, {
          keyboard_action: event.key.length === 1 ? 'typing' : 'editing'
        });
      }
      if (event.code === 'F12' || (event.code === 'KeyI' && event.ctrlKey && event.shiftKey)) {
        record('devtools', 'keydown');
      }
    });
  }

  function bindEditors() {
    // TinyMCE creates same-origin iframe documents asynchronously.
    for (const frame of document.querySelectorAll('iframe.tox-edit-area__iframe')) {
      try {
        if (frame.contentDocument) bindDocument(frame.contentDocument, true);
      } catch (_) { /* Cross-origin frames cannot be inspected. */ }
    }
  }

  async function start() {
    // Register only metadata. Event handlers read the live DOM when needed;
    // collecting events does not require copying or uploading the page HTML.
    const pageId = await post('/statistics/page', {
      page: location.href, browser: navigator.userAgent, title: document.title,
      window: {width: innerWidth, height: innerHeight}
    });
    if (!/^[a-f0-9]{24}$/i.test(pageId)) throw new Error('Invalid page ID');
    let tabID;
    try {
      tabID = sessionStorage.getItem('action-collector-tab');
      if (!tabID) {
        tabID = 'tab-' + Date.now() + '-' + Math.random().toString(36).slice(2);
        sessionStorage.setItem('action-collector-tab', tabID);
      }
    } catch (_) { tabID = 'tab-' + Date.now() + '-' + Math.random().toString(36).slice(2); }
    base = {...config.user, session_id: pageId, tabID, url: location.href};
    baseBytes = encoder.encode(JSON.stringify({...base, actions: []})).byteLength;
    state.ready = true;
    record('open', 'open page');
    bindDocument(document);
    bindEditors();
    document.addEventListener('visibilitychange', () => {
      record(document.visibilityState, 'visibilitychange');
      if (document.visibilityState === 'hidden') void flush();
    });
    window.addEventListener('pagehide', () => {
      if (closing) return;
      closing = true;
      record('close', 'close page');
      void flush(true);
    });
    window.addEventListener('pageshow', event => {
      if (event.persisted) { closing = false; record('open', 'open page'); }
    });
    setInterval(() => { void flush(); bindEditors(); }, 2000);
    void flush();
    console.info('[collector] ready');
  }

  async function run() {
    for (let attempt = 0; attempt < 3; attempt++) {
      try { await start(); state.error = null; return; }
      catch (error) {
        state.error = String(error);
        console.warn('[collector] initialization failed', error);
        if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 3000));
      }
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, {once: true});
  else void run();
})();
