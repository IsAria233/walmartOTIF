export const ROLES = ['dispute_associate', 'compliance_manager', 'admin'];
export const ROLE_LABELS = {dispute_associate: 'Dispute Associate', compliance_manager: 'Compliance Manager', admin: 'Admin'};
export function authApi(request) {
  return {
    login: (username, password) => request('/api/auth/login', {method: 'POST', body: {username, password}, authenticated: false}),
    me: () => request('/api/auth/me'),
  };
}
export function validateIdentity(value) {
  if (!value || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.user_id) || !ROLES.includes(value.role)) {
    throw new Error('The service returned an unsupported user identity. Please contact the team.');
  }
  return {user_id: value.user_id, role: value.role};
}
// Used only to expire UI state. Identity and permissions come from verified /me.
export function tokenExpiry(token) {
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const {exp} = JSON.parse(atob(part));
    if (!Number.isFinite(exp) || exp * 1000 <= Date.now()) throw new Error();
    return exp * 1000;
  } catch { throw new Error('The service returned an invalid or expired access token.'); }
}
