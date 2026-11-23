export class ApiError extends Error {
  constructor(message, status = 0, code = 'network_error') {
    super(message); this.name = 'ApiError'; this.status = status; this.code = code;
  }
}

function errorMessage(body, status) {
  if (typeof body?.error?.message === 'string') return body.error.message;
  if (typeof body?.detail === 'string') return body.detail;
  if (Array.isArray(body?.detail)) return 'Request data is invalid. Check the entered fields.';
  return ({401: 'Your session is invalid or expired. Please sign in again.', 403: 'You do not have permission for this action.', 503: 'The service is unavailable. Please try again later.'})[status] || 'The request failed. Please try again.';
}

// Per-provider client: no token or global callbacks leak between sessions.
export function createApiClient({getToken = () => null, onUnauthorized = () => {}, fetchImpl = (...args) => fetch(...args)} = {}) {
  return async function request(path, {method = 'GET', body, authenticated = true, signal, headers: extraHeaders = {}} = {}) {
    if (!path.startsWith('/api/') || path.startsWith('//')) throw new Error('Use a gateway API path');
    const token = authenticated ? getToken() : null;
    const headers = {...extraHeaders, Accept: 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    let response;
    try { response = await fetchImpl(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal, credentials: 'omit', cache: 'no-store'}); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new ApiError('Unable to reach the service. Check your connection and try again.');
    }
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      if (response.status === 401 && authenticated && token === getToken()) onUnauthorized();
      throw new ApiError(errorMessage(data, response.status), response.status, data?.error?.code || 'http_error');
    }
    if (data === null) throw new ApiError('The service returned an invalid response.', response.status, 'invalid_response');
    return data;
  };
}
