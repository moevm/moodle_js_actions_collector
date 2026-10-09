import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {startProxies, localUrl} from './local-proxy.mjs';

let servers = [];
let child;
function stop(signal) {
  child?.kill(signal);
  servers.forEach(server => server.close());
}
process.on('SIGTERM', () => stop('SIGTERM'));
process.on('SIGINT', () => stop('SIGINT'));
try {
  const manifest = JSON.parse(readFileSync('artifacts/demo.json', 'utf8'));
  const base = localUrl(process.env.MOODLE_URL);
  for (const key of ['reading', 'assignment', 'quiz', 'playground']) {
    if (localUrl(manifest[key]).origin !== base.origin) {
      throw new Error(`demo.json ${key} origin differs from MOODLE_URL`);
    }
  }
  servers = await startProxies(process.env);
  child = spawn(process.execPath, ['node_modules/@playwright/test/cli.js', 'test', ...process.argv.slice(2)], {
    stdio: 'inherit', env: process.env,
  });
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve(code ?? (signal === 'SIGINT' ? 130 : 143)));
  });
  process.exitCode = code;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  servers.forEach(server => server.close());
}
