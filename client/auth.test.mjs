import assert from 'node:assert/strict';
import {test} from 'node:test';
import {AxiosError} from 'axios';
import {clearSession, getAccessToken, saveSession, TOKEN_KEY} from './src/auth-state.mjs';
import {createApi} from './src/api.mjs';

function store() {
  const values = new Map();
  return {getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key)};
}

test('UI stores an access token and profile, never the login password', () => {
  const storage = store();
  saveSession({access_token: 'ui.test', name: 'Test', surname: 'User', position: 'admin', password: 'private'}, storage);
  assert.equal(getAccessToken(storage), 'ui.test');
  assert.equal(storage.getItem('password'), null);
  clearSession(storage);
  assert.equal(getAccessToken(storage), null);
  assert.equal(storage.getItem('name'), null);
});

test('API attaches tokens only to the collector origin and /api/ paths', async () => {
  const storage = store();
  storage.setItem(TOKEN_KEY, 'ui.private');
  const api = createApi({origin: 'https://collector.example', storage});
  const seen = [];
  api.defaults.adapter = async config => {
    seen.push(config.headers.get('Authorization'));
    return {status: 200, data: {}, headers: {}, config};
  };
  await api.get('/api/statistics/');
  await api.get('https://other.example/api/statistics/');
  await api.get('/unrelated');
  await api.get('/api/statistics/', {baseURL: 'https://other.example'});
  assert.deepEqual(seen, ['Bearer ui.private', undefined, undefined, undefined]);
});

test('expired API authentication clears the session and returns to login', async () => {
  const storage = store();
  storage.setItem(TOKEN_KEY, 'ui.expired');
  let redirects = 0;
  const api = createApi({origin: 'https://collector.example', storage, onUnauthorized: () => redirects++});
  api.defaults.adapter = async config => {
    throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, null, {status: 401, config});
  };
  await assert.rejects(api.get('/api/statistics/'));
  assert.equal(getAccessToken(storage), null);
  assert.equal(redirects, 1);
});
