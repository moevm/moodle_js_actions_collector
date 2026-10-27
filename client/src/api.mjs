import axios from 'axios';
import {clearSession, getAccessToken} from './auth-state.mjs';

export function createApi({
  origin = globalThis.location?.origin,
  storage = globalThis.sessionStorage,
  onUnauthorized = () => globalThis.location?.assign('/e.moevm.statistics/auth'),
} = {}) {
  const api = axios.create();
  const collectorRequest = config => {
    try {
      const url = new URL(api.getUri(config), origin);
      return url.origin === origin && url.pathname.startsWith('/api/');
    } catch { return false; }
  };
  api.interceptors.request.use(config => {
    const token = getAccessToken(storage);
    if (token && collectorRequest(config)) config.headers.Authorization = `Bearer ${token}`;
    return config;
  });
  api.interceptors.response.use(response => response, error => {
    if (error.response?.status === 401 && collectorRequest(error.config)
        && !String(error.config.url ?? '').includes('/auth/sign-in')) {
      clearSession(storage);
      onUnauthorized();
    }
    return Promise.reject(error);
  });
  return api;
}

export default createApi();
