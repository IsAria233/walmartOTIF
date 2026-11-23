import {isUUID} from './domain';
export const START_STATUSES = ['pending', 'investigating', 'revision_required', 'handed_off'];
export function validateRun(run, caseId) {
  if (!run || !isUUID(run.run_id) || run.case_id !== caseId || typeof run.status !== 'string') throw new Error('The Agent returned an invalid or unrelated Run response.');
  return run;
}
// Only recovery metadata is stored, never tokens, credentials or investigation text.
const attempts = new Map();
export function readAttempt(scope) {
  let value=attempts.get(scope) || null;
  try { value=JSON.parse(sessionStorage.getItem(`otif-attempt:${scope}`)) || value; } catch { /* Storage may be unavailable. */ }
  return value && isUUID(value.key) && typeof value.completed === 'boolean' && (!value.runId || isUUID(value.runId)) ? value : null;
}
export function saveAttempt(scope, value) {
  attempts.set(scope, value);
  try { sessionStorage.setItem(`otif-attempt:${scope}`, JSON.stringify(value)); } catch { /* In-memory recovery remains available. */ }
}
export function startRun(client, caseId, key) {
  return client('/api/agent/investigations', {method:'POST', body:{case_id:caseId}, headers:{'Idempotency-Key':key}}).then(run => validateRun(run,caseId));
}
