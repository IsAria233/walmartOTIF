import {createContext, useContext, useEffect, useState} from 'react';
import {createApiClient} from '../api/client';
import {authApi, tokenExpiry, validateIdentity} from '../api/auth';

class SessionRuntime {
  token = null;
  generation = 0;
  invalidate() { this.token = null; return ++this.generation; }
  setToken(token) { this.token = token; }
}
const AuthContext = createContext(null);
export function AuthProvider({children}) {
  const [runtime] = useState(() => new SessionRuntime());
  const [session, setSession] = useState({status: 'anonymous', user: null, expires: null, notice: ''});
  const [client] = useState(() => createApiClient({getToken: () => runtime.token, onUnauthorized: () => {
    runtime.invalidate();
    setSession({status: 'anonymous', user: null, expires: null, notice: 'Your session expired. Please sign in again.'});
  }}));
  function logout(notice = 'You have signed out.') {
    runtime.invalidate();
    setSession({status: 'anonymous', user: null, expires: null, notice});
  }
  useEffect(() => {
    if (!session.expires) return;
    const timeout = setTimeout(() => {
      runtime.invalidate();
      setSession({status: 'anonymous', user: null, expires: null, notice: 'Your session expired. Please sign in again.'});
    }, Math.min(session.expires - Date.now(), 2147483647));
    return () => clearTimeout(timeout);
  }, [session.expires, runtime]);
  async function login(username, password) {
    const attempt = runtime.invalidate();
    setSession({status: 'authenticating', user: null, expires: null, notice: ''});
    try {
      const api = authApi(client);
      const result = await api.login(username, password);
      if (attempt !== runtime.generation) return;
      if (result.token_type !== 'bearer' || typeof result.access_token !== 'string') throw new Error('The service returned an invalid login response.');
      const expires = tokenExpiry(result.access_token);
      runtime.setToken(result.access_token);
      const user = validateIdentity(await api.me());
      if (attempt !== runtime.generation) return;
      if (expires <= Date.now()) throw new Error('Your session expired. Please sign in again.');
      setSession({status: 'authenticated', user, expires, notice: 'Signed in successfully.'});
    } catch (error) {
      if (attempt === runtime.generation) { runtime.setToken(null); setSession({status: 'anonymous', user: null, expires: null, notice: ''}); }
      throw error;
    }
  }
  return <AuthContext.Provider value={{...session, login, logout, client}}>{children}</AuthContext.Provider>;
}
export function useAuth() { return useContext(AuthContext); }
