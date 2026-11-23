import {useRef, useState} from 'react';
import {useAuth} from '../auth/AuthContext';
import {domainPath} from '../api/domain';
import {ErrorState, Loading} from '../components/States';

// Policy section 3: the causes that apply to each fine type.
export const CAUSES = {
  on_time: [['C1', 'Supplier shipped late'], ['C2', 'DC changed the appointment']],
  in_full: [['C3', 'Supplier shipped short'], ['C4', 'DC receiving error'], ['C5', 'Fine used a superseded PO version']],
};
const REVIEWER_ROLES = ['dispute_associate', 'compliance_manager'];

/**
 * A reviewer decides the cause of a handed-off case. Domain stores the decision,
 * runs the rules engine and opens the approval; nothing is calculated here.
 */
export default function ManualResolution({caseRecord, onDone}) {
  const {client, user} = useAuth();
  const [open, setOpen] = useState(false);
  const [cause, setCause] = useState('');
  const [rationale, setRationale] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const causes = CAUSES[caseRecord.summary?.metric] || [];
  if (!REVIEWER_ROLES.includes(user.role)) return <p>Your role cannot resolve a handed-off Case.</p>;
  if (!causes.length) return <p>This fine type has no cause a reviewer can record here.</p>;
  async function submit(event) {
    event.preventDefault();
    if (lock.current || !cause || !rationale.trim()) return;
    lock.current = true; setBusy(true); setError('');
    try {
      await client(domainPath(`investigation-cases/${caseRecord.id}/manual-finding`), {method: 'POST', body: {cause_code: cause, rationale: rationale.trim()}});
      onDone(true);
    } catch (failure) {
      // The write may have been stored before the failure: reload so the Case shows its real state.
      setError(`${failure.message} The Case has been reloaded; check its status before trying again.`);
      onDone(false);
    } finally { lock.current = false; setBusy(false); }
  }
  if (!open) return <p><button className="btn primary" onClick={() => setOpen(true)}>Resolve manually</button></p>;
  return <form onSubmit={submit} aria-label="Resolve manually">
    <p>Record the cause you found. Accountability and amounts are then calculated by the rules engine, and the result still needs approval.</p>
    <label className="formline">Cause<select value={cause} onChange={e => setCause(e.target.value)} required disabled={busy}><option value="">Choose a cause</option>{causes.map(([code, label]) => <option key={code} value={code}>{code} · {label}</option>)}</select></label>
    <label className="formline">What you checked and found<textarea value={rationale} onChange={e => setRationale(e.target.value)} required maxLength={4000} disabled={busy}/></label>
    <div className="action-row"><button className="btn primary" disabled={busy}>Submit cause</button><button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>Cancel</button></div>
    {busy && <Loading message="Saving your decision…"/>}{error && <ErrorState message={error}/>}
  </form>;
}
