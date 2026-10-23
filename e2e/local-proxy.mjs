import http from 'node:http';

// Keep Moodle's canonical origins intact inside the test container. Forward
// real HTTP traffic to Docker services without rewriting bodies or redirects.
export function localUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname)
      || url.username || url.password) {
    throw new Error(`E2E supports local HTTP origins only: ${url.origin}`);
  }
  return url;
}

export function proxyRoutes(env) {
  const moodle = localUrl(env.MOODLE_URL);
  const collector = localUrl(env.COLLECTOR_URL);
  const api = localUrl(env.COLLECTOR_API_URL);
  const routes = new Map();
  function add(url, host, port) {
    const listenPort = Number(url.port || 80);
    const existing = routes.get(listenPort);
    if (existing && (existing.host !== host || existing.port !== port)) {
      throw new Error(`Conflicting local E2E ports: ${listenPort}`);
    }
    routes.set(listenPort, {host, port});
  }
  add(moodle, 'moodle', 80);
  add(collector, 'frontend', 8080);
  const directPort = Number(env.COLLECTOR_API_PORT);
  if (!Number.isInteger(directPort) || directPort < 1 || directPort > 65535) {
    throw new Error('Invalid COLLECTOR_API_PORT');
  }
  add(localUrl(`http://localhost:${directPort}`), 'backend', 8080);
  if (![Number(collector.port || 80), directPort].includes(Number(api.port || 80))) {
    throw new Error('COLLECTOR_API_URL must use the configured frontend or backend port');
  }
  return routes;
}

export function createProxy(target) {
  return http.createServer((request, response) => {
    const upstream = http.request({
      hostname: target.host, port: target.port,
      method: request.method, path: request.url,
      headers: request.headers, // Preserve Host, Origin, cookies and CORS behavior.
    }, incoming => {
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
      incoming.on('error', () => response.destroy());
    });
    upstream.setTimeout(30000, () => upstream.destroy(new Error('Upstream timeout')));
    upstream.on('error', () => {
      if (!response.headersSent) response.writeHead(502, {'Content-Type': 'text/plain'});
      response.end('E2E proxy could not reach the Docker service');
    });
    request.on('aborted', () => upstream.destroy());
    request.pipe(upstream);
  });
}

export async function startProxies(env) {
  const servers = [];
  try {
    for (const [port, target] of proxyRoutes(env)) {
      const server = createProxy(target);
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, resolve);
      });
      servers.push(server);
    }
    return servers;
  } catch (error) {
    servers.forEach(server => server.close());
    throw error;
  }
}
