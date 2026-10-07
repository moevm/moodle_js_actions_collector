/* Shared browser tracker. Configuration is supplied by the Moodle adapter. */
(() => {
  'use strict';
  const config = window.actionCollectorConfig;
  if (!config || window.actionCollector || !config.user) return;
  const api = config.apiUrl.replace(/\/$/, '');
  const state = {ready: false, queued: 0, sent: 0, error: null};
  window.actionCollector = state;
  let queue = [];
  let base;
  let flight;
  let closing = false;
  const documents = new WeakSet();

  async function post(path, body, keepalive = false) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(api + path, {
        method: 'POST', credentials: 'omit',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), keepalive, signal: controller.signal
      });
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timer); }
  }

  function flush(keepalive = true) {
    if (flight) return flight;
    if (!base || !queue.length) return Promise.resolve();
    flight = (async () => {
      while (queue.length) {
        const batch = queue.slice(0, 10);
        await post('/statistics/', {...base, actions: batch}, keepalive);
        queue.splice(0, batch.length);
        state.sent += batch.length;
        state.queued = queue.length;
        state.error = null;
      }
    })().catch(error => {
      state.error = String(error);
      console.warn('[collector] delivery failed', error);
    }).finally(() => { flight = null; });
    return flight;
  }
  state.flush = flush;

  function record(action, event, type = 'page', name = 'page') {
    queue.push({
      timestamp: new Date().toISOString(), action_type: action, event_type: event,
      element_type: type, element_name: String(name).slice(0, 160),
      // Do not transmit field contents, passwords or clipboard text.
      element_html: type === 'page' ? '' : '<' + type + '>'
    });
    state.queued = queue.length;
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
    let lastScroll = 0;
    doc.addEventListener('scroll', () => {
      if (Date.now() - lastScroll < 1000) return;
      lastScroll = Date.now();
      record('conversation', 'scroll', editor ? 'editor' : 'page');
    }, {capture: true, passive: true});
    doc.addEventListener('keydown', event => {
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
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('script,style,input,textarea,select,[contenteditable="true"],iframe')
      .forEach(node => node.remove());
    const pageId = await post('/statistics/page', {
      page: location.href, browser: navigator.userAgent, title: document.title,
      page_html: clone.outerHTML.slice(0, 200000),
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
    state.ready = true;
    record('open', 'open page');
    bindDocument(document);
    bindEditors();
    document.addEventListener('visibilitychange', () => {
      record(document.visibilityState, 'visibilitychange');
      if (document.visibilityState === 'hidden') void flush(true);
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
