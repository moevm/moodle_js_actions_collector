import {test} from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createProxy, proxyRoutes, localUrl} from './local-proxy.mjs';

const defaults = {
  MOODLE_URL: 'http://localhost:18082',
  COLLECTOR_URL: 'http://localhost:18081',
  COLLECTOR_API_URL: 'http://localhost:18081/api',
  COLLECTOR_API_PORT: '18080',
};
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const close = server => new Promise(resolve => {
  server.close(resolve);
  server.closeAllConnections();
});

test('local canonical origins map to three distinct Docker services', () => {
  assert.deepEqual([...proxyRoutes(defaults)], [
    [18082, {host: 'moodle', port: 80}],
    [18081, {host: 'frontend', port: 8080}],
    [18080, {host: 'backend', port: 8080}],
  ]);
  assert.doesNotThrow(() => proxyRoutes({...defaults, COLLECTOR_API_URL: 'http://127.0.0.1:18080/api'}));
});

test('custom local ports are supported', () => {
  assert.equal(proxyRoutes({...defaults, MOODLE_URL: 'http://localhost:19082/moodle'}).get(19082).host, 'moodle');
});

test('external targets, credentials and ambiguous ports fail before a test starts', () => {
  for (const value of ['https://localhost:18082', 'http://prod.example.org', 'http://user:secret@localhost']) {
    assert.throws(() => localUrl(value));
  }
  assert.throws(() => proxyRoutes({...defaults, MOODLE_URL: defaults.COLLECTOR_URL}), /Conflicting/);
  assert.throws(() => proxyRoutes({...defaults, COLLECTOR_API_URL: 'http://localhost:18082/api'}));
  assert.throws(() => proxyRoutes({...defaults, COLLECTOR_API_PORT: 'invalid'}));
});

test('proxy preserves real request body, Host, Origin, cookies, redirects and CORS', async () => {
  const payload = JSON.stringify({actions: [{event_type: 'paste'}]});
  let received;
  const upstream = http.createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    received = {body: Buffer.concat(chunks).toString(), url: request.url, method: request.method, headers: request.headers};
    response.writeHead(302, {
      Location: 'http://localhost:18082/login/index.php',
      'Set-Cookie': 'MoodleSession=next; Path=/; HttpOnly',
      'Access-Control-Allow-Origin': 'http://localhost:18082',
    });
    response.end('unchanged body');
  });
  await listen(upstream);
  const proxy = createProxy({host: '127.0.0.1', port: upstream.address().port});
  await listen(proxy);
  try {
    const response = await new Promise((resolve, reject) => {
      const request = http.request({
        host: '127.0.0.1', port: proxy.address().port, path: '/api/statistics/?page=1',
        method: 'POST',
        headers: {Host: 'localhost:18081', Origin: 'http://localhost:18082', Cookie: 'MoodleSession=example'},
      }, incoming => {
        const chunks = [];
        incoming.on('data', chunk => chunks.push(chunk));
        incoming.on('end', () => resolve({status: incoming.statusCode, headers: incoming.headers, body: Buffer.concat(chunks).toString()}));
      });
      request.on('error', reject);
      request.end(payload);
    });
    assert.equal(received.body, payload);
    assert.equal(received.url, '/api/statistics/?page=1');
    assert.equal(received.method, 'POST');
    assert.equal(received.headers.host, 'localhost:18081');
    assert.equal(received.headers.origin, 'http://localhost:18082');
    assert.equal(received.headers.cookie, 'MoodleSession=example');
    assert.equal(response.status, 302);
    assert.equal(response.headers.location, 'http://localhost:18082/login/index.php');
    assert.equal(response.headers['access-control-allow-origin'], 'http://localhost:18082');
    assert.match(response.headers['set-cookie'][0], /MoodleSession=next/);
    assert.equal(response.body, 'unchanged body');
  } finally {
    await close(proxy);
    await close(upstream);
  }
});

test('unreachable service produces a visible failure instead of a fake success', async () => {
  const unused = http.createServer();
  await listen(unused);
  const port = unused.address().port;
  await close(unused);
  const proxy = createProxy({host: '127.0.0.1', port});
  await listen(proxy);
  try {
    const response = await fetch(`http://127.0.0.1:${proxy.address().port}/`);
    assert.equal(response.status, 502);
  } finally {
    await close(proxy);
  }
});
