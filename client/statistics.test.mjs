import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

// Execute the actual SFC's Options API methods. HTTP promises are controlled
// explicitly to cover response orders that a real network is free to produce.
function setup() {
  const requests = [];
  const api = {get(url, config) {
    let resolve, reject;
    const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    requests.push({url, config, resolve, reject});
    return promise;
  }};
  const source = readFileSync(new URL('./src/components/Pages/StatisticsPage.vue', import.meta.url), 'utf8');
  const script = source.split('<script>')[1].split('</script>')[0];
  const names = [];
  const body = script.replace(/^import (\w+) from ["'][^"']+["'];?\s*$/gm, (_, name) => {
    names.push(name); return '';
  }).replace('export default', 'return');
  const errors = [];
  const component = new Function(...names, 'console', body)(
    ...names.map(name => name === 'axios' ? api : {}), {error: (...args) => errors.push(args)});
  const state = component.data();
  for (const [name, method] of Object.entries(component.methods)) state[name] = method.bind(state);
  return {state, requests, errors, component};
}

function response(id, total = 1) {
  return {data: [[{student_id: id, student: `Student ${id}`, email: `${id}@example.com`,
    course: 'Course', url: `https://moodle.example/${id}`, tabID: `tab-${id}`,
    actions: [{event_type: 'mousedown', action_type: 'conversation', element_type: 'button',
      element_name: `button-${id}`, timestamp: '2026-10-27T00:00:00Z'}]}], total]};
}

test('responses 2 then 1 cannot mix rows, filters or totals', async () => {
  const {state, requests} = setup();
  state.ID = '101';
  const first = state.getStatistics();
  state.ID = '202';
  state.pageSize = 25;
  const second = state.getStatistics();
  assert.equal(requests[0].config.signal.aborted, true);
  // The fake transport deliberately still resolves an aborted request.
  requests[1].resolve(response(202, 51)); await second;
  requests[0].resolve(response(101, 999)); await first;
  assert.deepEqual(state.statisticsInfo.map(row => row.studentId), [202]);
  assert.equal(state.params.student_id, 202);
  assert.equal(state.count, 51);
  assert.equal(state.totalPages, 3);
  assert.equal(state.statisticsLoading, false);
});

test('responses 3 then 1 then 2 leave only the third selection visible', async () => {
  const {state, requests} = setup();
  const pending = [1, 2, 3].map(id => {state.ID = String(id); return state.getStatistics();});
  for (const index of [2, 0, 1]) {requests[index].resolve(response(index + 1)); await pending[index];}
  assert.deepEqual(state.statisticsInfo.map(row => row.studentId), [3]);
});

test('stale errors do not overwrite current success or stop a new loading state', async () => {
  const {state, requests, errors} = setup();
  const first = state.getStatistics();
  const second = state.getStatistics();
  requests[0].reject(new Error('Old request failed')); await first;
  assert.equal(state.statisticsLoading, true);
  assert.equal(state.statisticsError, '');
  requests[1].resolve(response(2)); await second;
  assert.deepEqual(state.statisticsInfo.map(row => row.studentId), [2]);
  assert.deepEqual(errors, []);
});

test('reset during loading starts a new unfiltered first page', async () => {
  const {state, requests} = setup();
  state.ID = '101'; state.page = 7;
  const first = state.getStatistics();
  const reset = state.resetSearch();
  assert.equal(requests[0].config.signal.aborted, true);
  assert.equal(requests[1].config.params.page, 1);
  assert.equal('student_id' in requests[1].config.params, false);
  requests[1].resolve(response(202)); await reset;
  requests[0].resolve(response(101)); await first;
  assert.deepEqual(state.statisticsInfo.map(row => row.studentId), [202]);
});

test('pagination uses captured request values and params do not change with input', async () => {
  const {state, requests} = setup();
  state.pageSize = 10; state.FIO = 'Иван [Тест]';
  const pending = state.getStatistics();
  state.pageSize = 100; state.FIO = 'another value';
  requests[0].resolve(response(1, 21)); await pending;
  assert.equal(state.totalPages, 3);
  assert.equal(requests[0].config.params.student_name, 'Иван [Тест]');
  assert.equal(requests[0].config.params.pageSize, 10);
});

test('unmount aborts the request and prevents later state commits', async () => {
  const {state, requests, component} = setup();
  const pending = state.getStatistics();
  component.beforeUnmount.call(state);
  assert.equal(requests[0].config.signal.aborted, true);
  requests[0].resolve(response(1)); await pending;
  assert.deepEqual(state.statisticsInfo, []);
});

test('current request failures clear old data and expose an error', async () => {
  const {state, requests} = setup();
  state.statisticsInfo = [{studentId: 1}];
  const pending = state.getStatistics();
  assert.deepEqual(state.statisticsInfo, []);
  requests[0].reject({response: {status: 422}}); await pending;
  assert.match(state.statisticsError, /фильтров/);
  assert.equal(state.statisticsLoading, false);
});
