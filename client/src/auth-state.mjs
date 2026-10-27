export const TOKEN_KEY = 'collector.access_token';

export function getAccessToken(storage = globalThis.sessionStorage) {
  try { return storage.getItem(TOKEN_KEY); }
  catch { return null; }
}

export function clearSession(storage = globalThis.sessionStorage) {
  for (const key of [TOKEN_KEY, 'name', 'position']) {
    try { storage.removeItem(key); }
    catch { /* An unavailable store must not prevent returning to login. */ }
  }
}

export function saveSession(session, storage = globalThis.sessionStorage) {
  if (typeof session.access_token !== 'string' || !session.access_token.startsWith('ui.')) {
    throw new Error('Сервер не вернул токен доступа');
  }
  clearSession(storage);
  try {
    storage.setItem(TOKEN_KEY, session.access_token);
    storage.setItem('name', `${session.name} ${session.surname}`);
    storage.setItem('position', session.position);
  } catch {
    clearSession(storage);
    throw new Error('Не удалось сохранить сеанс в браузере');
  }
}
