import {useEffect, useRef, useState} from 'react';
import {useAuth} from '../auth/AuthContext';
import useRead from '../hooks/useRead';
import {domainPath, isUUID} from '../api/domain';
import {allPages, pendingStage, preflight, recoveryRead, recoverySave, resumeDecision, STAGE_ROLES} from '../api/approval';
import {ErrorState, Loading} from '../components/States';
import {Money, Pagination, pretty, ReadState, Timestamp} from '../components/Records';

function DecisionHistory({items}) {
  return <><h4>Human decision history</h4>{!items.length && <p>No approval stages recorded.</p>}{items.map(({approval,decisions})=><div className="decision-history" key={approval.id}><strong>{pretty(approval.approval_type)}: {pretty(approval.status)}</strong>{decisions.map(item=><div key={item.id}><p>{pretty(item.decision)} · <Timestamp value={item.decided_at}/></p><p className="record-id">Reviewer: {item.auth_user_id}</p><p>{item.comment || 'No comment recorded.'}</p></div>)}</div>)}</>;
}
function LineDecision({line,outcome,caseRecord,approvals,current,ready,onRefresh}) {
  const {client,user}=useAuth();
  const stage=pendingStage(line,approvals);
  const scope=`${user.user_id}:${outcome.id}:${line.id}`;
  const [recovery,setRecovery]=useState(()=>recoveryRead(scope));
  const [choice,setChoice]=useState('');const [comment,setComment]=useState('');
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [message,setMessage]=useState('');
  const lock=useRef(false);const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const blocked=recovery && (recovery.kind==='uncertain' || !recovery.resumeDone || recovery.approvalId===stage?.approval.id);
  const writable=current && ready && caseRecord.status==='awaiting_approval' && ['pending_approval','pending_manager_approval'].includes(outcome.status) && stage && STAGE_ROLES[stage.approval.approval_type]?.includes(user.role);
  function save(value, approvalId = recovery?.approvalId || stage?.approval.id) {const stored={...value,approvalId};recoverySave(scope,stored);if(mounted.current)setRecovery(stored);}
  async function authoritativeRefresh() {
    await Promise.all([client(domainPath(`investigation-cases/${caseRecord.id}`)),client(domainPath(`investigation-cases/${caseRecord.id}/outcome`,{page:1,page_size:20})),allPages(client,domainPath(`outcomes/${outcome.id}/approvals`))]);
    if(mounted.current)onRefresh();
  }
  async function resume() {
    if(lock.current)return;lock.current=true;setBusy(true);setError('');
    try {await authoritativeRefresh();const text=await resumeDecision(client,caseRecord.id,outcome.id,line.finding_id);if(mounted.current)setMessage(text);save({kind:'recorded',resumeDone:true});}
    catch(failure){if(mounted.current)setError(`Domain decision is recorded; follow-up failed. ${failure.message}`);}
    finally{lock.current=false;if(mounted.current)setBusy(false);}
  }
  async function confirm(event) {
    event.preventDefault();if(lock.current || !writable || blocked)return;
    if(choice==='rejected' && !comment.trim()){setError('A rejection reason is required.');return;}
    lock.current=true;setBusy(true);setError('');let submitted=false;let recorded=false;
    try {
      const name=await preflight(client,caseRecord.id,outcome.id,line.id,stage.approval.id,user.role);
      if(!mounted.current)return;
      submitted=true;setChoice('');setComment('');recoverySave(scope,{kind:'uncertain',approvalId:stage.approval.id});setRecovery({kind:'uncertain',approvalId:stage.approval.id});
      const decisionRecord=await client(domainPath(`outcomes/${outcome.id}/approvals`),{method:'POST',body:{line_outcome_id:line.id,stage:name,decision:choice,comment:comment.trim()||null}});
      if(!isUUID(decisionRecord.id) || decisionRecord.approval_id!==stage.approval.id || decisionRecord.auth_user_id!==user.user_id || decisionRecord.decision!==choice)throw new Error('The service returned an unconfirmed decision response. Check authoritative history.');
      recorded=true;save({kind:'recorded',resumeDone:false},stage.approval.id);if(mounted.current){setChoice('');setMessage('Domain decision recorded. Refreshing authoritative state…');}
      await authoritativeRefresh();const text=await resumeDecision(client,caseRecord.id,outcome.id,line.finding_id);save({kind:'recorded',resumeDone:true},stage.approval.id);if(mounted.current)setMessage(text);
    } catch(failure) {
      if(mounted.current)setError(`${recorded?'Domain decision recorded; follow-up failed. ':submitted?'The approval result may be uncertain. Do not submit it again. ':'Approval not submitted. '}${failure.message}`);
      if(mounted.current)onRefresh();
    } finally{lock.current=false;if(mounted.current)setBusy(false);}
  }
  async function reconcile() {
    if(lock.current)return;lock.current=true;setBusy(true);setError('');
    try {
      const rows=await allPages(client,domainPath(`outcomes/${outcome.id}/approvals`));
      const saved=rows.find(item=>item.approval.line_outcome_id===line.id && item.approval.id===recovery?.approvalId);
      if(!saved?.decisions.length)throw new Error('No completed decision is confirmed yet. Keep this write blocked and check again later.');
      save({kind:'recorded',resumeDone:false});if(mounted.current)setMessage('A recorded decision is confirmed. Agent resume can be retried separately.');onRefresh();
    }catch(failure){if(mounted.current)setError(failure.message);}
    finally{lock.current=false;if(mounted.current)setBusy(false);}
  }
  return <section className="line-review"><h3>Line Outcome · {line.evaluated_line_key}</h3><p className="record-id">{line.id}</p><div className="kvgrid"><div>Disposition: <strong>{pretty(line.outcome)}</strong></div><div>Accountable: <strong>{pretty(line.accountable_party)}</strong></div><div>Policy: {line.policy_version}</div><div>Finding: <span className="record-id">{line.finding_id}</span></div></div><p>{line.rationale}</p>
    <div className="moneyrow"><span>Original fine</span><strong><Money value={line.original_amount}/></strong></div><div className="moneyrow"><span>Corrected fine</span><strong><Money value={line.corrected_amount}/></strong></div><div className="moneyrow highlight"><span>Reversal</span><strong><Money value={line.reversal_amount}/></strong></div><p>Calculated <Timestamp value={line.calculated_at}/></p>
    <div className="section-label">Human decision</div><p>Line approval state: {pretty(line.approval_status)}</p>{stage && <p>Pending stage: <strong>{pretty(stage.approval.approval_type)}</strong></p>}
    {!current && <p>Historical Outcome — read-only.</p>}{stage && !STAGE_ROLES[stage.approval.approval_type]?.includes(user.role) && <p>Your role cannot decide this approval stage.</p>}
    {writable && !blocked && <>{!choice ? <div className="action-row"><button className="btn outlinegreen" onClick={()=>setChoice('approved')}>Approve line</button><button className="btn outlinered" onClick={()=>setChoice('rejected')}>Reject line</button></div> : <form onSubmit={confirm} aria-label={`Confirm decision ${line.id}`}><p>Confirm {choice==='approved'?'approval':'rejection'} at the {stage.approval.approval_type} stage for this Line Outcome.</p><label className="formline">Decision comment<textarea value={comment} onChange={e=>setComment(e.target.value)} required={choice==='rejected'} disabled={busy}/></label><div className="action-row"><button className="btn primary" disabled={busy}>Confirm {choice==='approved'?'approve':'reject'}</button><button type="button" className="btn" disabled={busy} onClick={()=>setChoice('')}>Cancel decision</button></div></form>}</>}
    {busy && <Loading message="Saving decision or reconciling authoritative state…"/>}{message && <p role="status">{message}</p>}{error && <ErrorState message={error}/>}
    {recovery?.kind==='uncertain' && <><p>Decision result is uncertain. Approval resubmission is blocked.</p>{current && <button className="btn" disabled={busy || !ready} onClick={reconcile}>Check decision state</button>}</>}
    {recovery?.kind==='recorded' && <><p>Domain decision recorded.</p>{current && !recovery.resumeDone && <button className="btn" disabled={busy || !ready} onClick={resume}>Retry Agent resume</button>}</>}
    <DecisionHistory items={approvals.filter(item=>item.approval.line_outcome_id===line.id)}/>
  </section>;
}
function SelectedOutcome({item,current,caseRecord,refreshVersion,onRefresh,ready}) {
  const {client}=useAuth();const [approvals,setApprovals]=useState(null);const [failure,setFailure]=useState(null);
  const outcome=item.outcome;
  const evaluation=useRead(domainPath(`evaluations/${outcome.evaluation_id}`),false,{refreshKey:refreshVersion});
  const finding=useRead(evaluation.data?domainPath(`findings/${evaluation.data.finding_id}`):null,false);
  useEffect(()=>{let active=true;allPages(client,domainPath(`outcomes/${outcome.id}/approvals`)).then(rows=>{if(active)setApprovals({version:refreshVersion,rows});}).catch(error=>{if(active)setFailure({version:refreshVersion,error});});return()=>{active=false;};},[client,outcome.id,refreshVersion]);
  const loaded=approvals?.version===refreshVersion;
  const error=failure?.version===refreshVersion?failure.error:null;
  return <><h3>{current?'Current':'Historical'} Outcome</h3><p className="record-id">{outcome.id}</p><p>Aggregate status: {pretty(outcome.status)}</p><div className="section-label">Deterministic Domain evaluation</div><ReadState resource={evaluation}>{evaluation.data && <><p>Evaluation version: {evaluation.data.version_number} · Policy: {evaluation.data.policy_version}</p><p className="record-id">Evaluation: {evaluation.data.id} · Finding: {evaluation.data.finding_id}</p><p>Evaluated <Timestamp value={evaluation.data.evaluated_at}/></p><details><summary>Persisted calculation snapshot</summary><pre>{JSON.stringify({result:evaluation.data.result,inputs:evaluation.data.calculation_inputs,outputs:evaluation.data.calculation_outputs},null,2)}</pre></details></>}</ReadState>
    {finding.data?.id===evaluation.data?.finding_id && finding.data?.investigation_case_id===caseRecord.id && <p>Related Agent cause: {finding.data.cause_code || 'Not supplied'} (assessment, not human approval).</p>}{finding.error && <ErrorState message={finding.error.message} onRetry={finding.refresh}/>}
    {!loaded && !error && <Loading message="Loading approval history…"/>}{error && <ErrorState message={error.message} onRetry={onRefresh}/>}
    {item.line_outcomes.map(line=><LineDecision key={line.id} line={line} outcome={outcome} caseRecord={caseRecord} current={current} ready={ready && line.case_outcome_id===outcome.id && line.investigation_case_id===caseRecord.id && outcome.investigation_case_id===caseRecord.id && loaded && !error && !!evaluation.data && evaluation.data.id===outcome.evaluation_id && evaluation.data.investigation_case_id===caseRecord.id && evaluation.data.finding_id===line.finding_id} approvals={approvals?.rows || []} onRefresh={onRefresh}/>)}
  </>;
}
export default function OutcomeReview({caseRecord,refreshVersion,onRefresh,metric}) {
  const [page,setPage]=useState(1);const [evaluationPage,setEvaluationPage]=useState(1);const [selected,setSelected]=useState('');
  const resource=useRead(domainPath(`investigation-cases/${caseRecord.id}/outcome`,{page,page_size:20}),true,{keepPrevious:true,refreshKey:refreshVersion});
  const evaluations=useRead(domainPath(`investigation-cases/${caseRecord.id}/evaluations`,{page:evaluationPage,page_size:20}),true,{refreshKey:refreshVersion});
  const item=resource.data?.items.find(item=>item.outcome.id===selected) || resource.data?.items[0];
  const current=page===1 && item?.outcome.id===resource.data?.items[0]?.outcome.id;
  return <><h2>Outcome & Approval</h2><p>Fine metric: {pretty(metric)}. Amounts below are persisted Domain calculations; no fine is calculated in this browser.</p><button className="btn small" onClick={onRefresh}>Refresh authoritative state</button>
    {resource.loading && <Loading message="Loading Outcomes…"/>}{resource.error && <ErrorState message={resource.error.message} onRetry={resource.refresh}/>}
    {!resource.loading && !resource.error && !resource.data?.items.length && <p>No Outcome available.</p>}
    {resource.data && <><label className="formline">Outcome version<select value={item?.outcome.id || ''} onChange={e=>setSelected(e.target.value)}>{resource.data.items.map(row=><option key={row.outcome.id} value={row.outcome.id}>{row.outcome.id} · {row.outcome.status}</option>)}</select></label>{item && <SelectedOutcome key={item.outcome.id} item={item} current={current} caseRecord={caseRecord} refreshVersion={refreshVersion} ready={!resource.loading && !resource.error} onRefresh={onRefresh}/>}<Pagination data={resource.data} onPage={value=>{setPage(value);setSelected('');}}/></>}
    <details><summary>Available Evaluation history</summary><p>Record history is not a complete audit log. Evaluation pages are ordered by version ascending; Outcome pages by creation descending.</p><ReadState resource={evaluations} empty="No Evaluations available">{evaluations.data && <>{evaluations.data.items.map(item=><details key={item.id}><summary>Evaluation v{item.version_number} · {item.id}</summary><p>Finding: {item.finding_id} · Policy: {item.policy_version}</p><Timestamp value={item.evaluated_at}/><pre>{JSON.stringify(item,null,2)}</pre></details>)}<Pagination data={evaluations.data} onPage={setEvaluationPage}/></>}</ReadState></details>
  </>;
}
