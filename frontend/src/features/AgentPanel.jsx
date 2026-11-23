import {useEffect, useRef, useState} from 'react';
import {useAuth} from '../auth/AuthContext';
import {readAttempt, saveAttempt, startRun, START_STATUSES, validateRun} from '../api/agent';
import {isUUID, UUID_PATTERN} from '../api/domain';
import useRead from '../hooks/useRead';
import {ErrorState, Loading} from '../components/States';
import {pretty} from '../components/Records';
import {AgentAssessment, ToolActivity} from './Assessment';

export default function AgentPanel({caseRecord, suggestedRunId, onComplete}) {
  const {client,user} = useAuth();
  const scope=`${user.user_id}:${caseRecord.id}`;
  const [attempt,setAttempt] = useState(() => readAttempt(scope));
  const [knownId,setKnownId] = useState(() => readAttempt(scope)?.runId || '');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [started,setStarted] = useState(null);
  const lock=useRef(false);
  const mounted=useRef(true);
  useEffect(() => { mounted.current=true;return () => { mounted.current=false; }; },[]);
  const read=useRead(isUUID(knownId) ? `/api/agent/investigations/${knownId}` : null,false);
  let run=started;
  let readError='';
  if (read.data) { try {run=validateRun(read.data,caseRecord.id);} catch(failure) {readError=failure.message;} }
  const eligible=START_STATUSES.includes(caseRecord.status);
  // An unresolved attempt is always retried with its original key, even if
  // a partial server-side write has changed the Case status.
  const uncertain=!!attempt && !attempt.completed;
  const canStart=uncertain || (eligible && (!attempt?.completed || ['handed_off','revision_required'].includes(caseRecord.status)));
  async function start() {
    if(lock.current || !canStart) return;
    lock.current=true;setBusy(true);setError('');
    const next=uncertain ? attempt : {key:crypto.randomUUID(),completed:false};
    saveAttempt(scope,next);setAttempt(next);
    try {
      const result=await startRun(client,caseRecord.id,next.key);
      const complete={...next,completed:true,runId:result.run_id};saveAttempt(scope,complete);
      if(mounted.current) {setAttempt(complete);setStarted(result);setKnownId(result.run_id);onComplete();}
    } catch(failure) { if(mounted.current) setError(`${failure.message} The result may be uncertain. Retry uses the same investigation key.`); }
    finally {lock.current=false;if(mounted.current)setBusy(false);}
  }
  function load(event) {event.preventDefault();const value=new FormData(event.currentTarget).get('run_id').trim();if(isUUID(value)){setKnownId(value);setStarted(null);read.refresh();}}
  return <section className="card agent-panel"><div className="cardhead"><h2>Agent investigation</h2></div><div className="inner">
    <p>Starting an investigation reads the Case records and may submit Findings and a calculated Outcome. It pauses for human review or records a handoff; it does not approve a decision.</p>
    {canStart ? <button className="btn primary" onClick={start} disabled={busy}>{busy?'Investigation request running…':uncertain?'Retry same investigation':attempt?.completed?'Start new investigation':'Start investigation'}</button> : <p>No new investigation can be started from the current Case state.</p>}
    {busy && <Loading message="Waiting for the Agent response. This may take several minutes; progress is not streamed."/>}
    {error && <ErrorState message={error}/>}
    {attempt && <p className="annotation record-id">Recovery key: {attempt.key}</p>}
    <form className="run-form" onSubmit={load}><label>Known Run ID<input name="run_id" key={knownId} defaultValue={knownId} required pattern={UUID_PATTERN} title="Enter a Run UUID"/></label><button className="btn small" disabled={busy}>View Run</button></form>
    {suggestedRunId && <button className="btn small" onClick={() => {setStarted(null);setKnownId(suggestedRunId);read.refresh();}} disabled={busy}>View recorded Run</button>}
    {knownId && <div><p className="record-id">Run ID: {knownId}</p><button className="btn small" onClick={read.refresh} disabled={busy || read.loading}>Refresh Run</button></div>}
    {read.loading && <Loading message="Loading Run details…"/>}{read.error && <ErrorState message={read.error.message} onRetry={read.refresh}/>} {readError && <ErrorState message={readError}/>}
    {run && !readError && <div className="run-result"><h3>Agent Run result</h3><p>Status: <strong>{pretty(run.status)}</strong></p><p>{run.paused_for_approval ? 'Paused for human approval.' : run.unfinished ? 'Unfinished run; recovery may be needed.' : 'No pending execution reported.'}</p>{run.handoff_reason && <p>Handoff: {run.handoff_reason}</p>}<p>Model steps: {run.model_steps ?? 'Not supplied'}</p>{run.trace_id && <p className="record-id">Trace ID: {run.trace_id}</p>}
      {run.findings && <details><summary>Agent Run assessment (not a human decision)</summary><AgentAssessment findings={run.findings}/></details>}
      {!!run.tool_log?.length && <details><summary>Recorded tool activity</summary><ToolActivity log={run.tool_log}/></details>}
    </div>}
  </div></section>;
}
