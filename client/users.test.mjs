import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

function setup() {
  const requests = [];
  const api = {post(url, data) {
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    requests.push({url, data, resolve, reject});
    return promise;
  }};
  const source = readFileSync(new URL('./src/components/Pages/CreateUserPage.vue', import.meta.url), 'utf8');
  const script = source.split('<script>')[1].split('</script>')[0];
  const names = [];
  const body = script.replace(/^import (\w+) from ["'][^"']+["'];?\s*$/gm, (_, name) => {
    names.push(name); return '';
  }).replace('export default', 'return');
  const component = new Function(...names, 'console', body)(
    ...names.map(name => name === 'axios' ? api : {}), {error() {}});
  const state = {...component.data(), email: 'new@example.com', name: 'New',
    surname: 'User', lastname: 'Test', password: 'example-password'};
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state);
  return {state, requests};
}

for (const status of [409, 422, 503, 507]) {
  test(`HTTP ${status} preserves the entered fields and displays a message`, async () => {
    const {state, requests} = setup();
    const pending = state.createUser();
    requests[0].reject({response: {status}}); await pending;
    assert.equal(state.email, 'new@example.com');
    assert.equal(state.name, 'New');
    assert.equal(state.password, 'example-password');
    assert.notEqual(state.errorMessage, '');
    if (status === 409) assert.match(state.errorMessage, /уже существует/);
    assert.equal(state.creating, false);
  });
}

test('network failure preserves input and permits retry', async () => {
  const {state, requests} = setup();
  const first = state.createUser();
  requests[0].reject(new Error('Connection failed')); await first;
  assert.equal(state.email, 'new@example.com');
  const second = state.createUser();
  requests[1].resolve({data: {id: 'new-user'}}); await second;
  assert.equal(state.email, '');
  assert.equal(state.password, '');
  assert.equal(state.errorMessage, '');
});

test('repeated clicks send only one active creation request', async () => {
  const {state, requests} = setup();
  const pending = state.createUser();
  await state.createUser();
  assert.equal(requests.length, 1);
  assert.equal(state.creating, true);
  requests[0].resolve({data: {id: 'new-user'}}); await pending;
  assert.equal(state.creating, false);
});
