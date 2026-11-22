const ROOT = '/api/domain/v1';
export const CASE_STATUSES = ['pending', 'investigating', 'findings_submitted', 'awaiting_approval', 'handed_off', 'revision_required', 'closed'];
export const ORIGINS = ['supplier_dispute', 'pre_invoice_scan'];
export const UUID_PATTERN = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
export const isUUID = value => new RegExp(`^${UUID_PATTERN}$`).test(value);
export function domainPath(resource, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== '' && value != null) query.set(key, value);
  return `${ROOT}/${resource}${query.size ? `?${query}` : ''}`;
}
export function validatePage(data) {
  if (!data || !Array.isArray(data.items) || !['page', 'page_size', 'total', 'total_pages'].every(key => Number.isSafeInteger(data[key])) || data.page < 1 || data.page_size < 1 || data.total < 0 || data.total_pages < 0) {
    throw new Error('The service returned an invalid page response. Please try again.');
  }
  return data;
}
export function positiveInt(value, fallback) {
  return /^\d+$/.test(value || '') && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback;
}
