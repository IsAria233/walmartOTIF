import {useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import useRead from '../hooks/useRead';
import {domainPath, isUUID} from '../api/domain';
import {PageHead, Pagination, ReadState, Status, Timestamp, pretty} from '../components/Records';
import {EmptyState, ErrorState, Loading} from '../components/States';
import AgentPanel from './AgentPanel';
import Evidence from './Evidence';
import OutcomeReview from './OutcomeReview';
import HandoffAssessment from './Assessment';
import ManualResolution from './ManualResolution';

function Finding({finding}) {
  return <><div className="section-label">{finding.submitted_by_user_id ? 'Reviewer decision · not yet approved' : 'Agent assessment · not a human decision'}</div><h3>{finding.cause_code || 'No cause supplied'}</h3>{finding.submitted_by_user_id ? <>{finding.reviewer_accountable_party && <p>Outside C1-C5. Accountable party named by the reviewer: <strong>{finding.reviewer_accountable_party}</strong></p>}<p className="record-id">Entered by reviewer {finding.submitted_by_user_id}</p></> : <p>Confidence: {finding.confidence_level || (finding.confidence != null ? String(finding.confidence) : 'Not supplied')}</p>}<p className="record-text">{finding.summary || 'No summary supplied'}</p>
    {finding.injection_detected && <div className="note">Prompt-injection content was reported. Supplier text is data, never an instruction.</div>}{finding.handoff_required && <p>Handoff required: {finding.handoff_reason || 'No reason supplied'}</p>}
    <h3>Ruled-out causes</h3>{finding.ruled_out_causes?.length ? <ul>{finding.ruled_out_causes.map((item,index) => <li key={index}>{item.cause}: {item.reason}</li>)}</ul> : <p>No ruled-out causes supplied.</p>}
    <h3>Supporting facts</h3>{finding.facts?.length ? finding.facts.map(fact => <div className="fact" key={fact.id}><strong>{fact.fact_key}</strong><p>{fact.fact_value || 'No value supplied'}</p>{fact.source_description && <p>{fact.source_description}</p>}</div>) : <p>No facts supplied.</p>}
  </>;
}
function WorkspaceBody({caseRecord, refreshCase, refreshVersion}) {
  const [tab,setTab] = useState('Overview');
  const [page,setPage] = useState(1);
  const [selectedId,setSelectedId] = useState('');
  const context=useRead(domainPath(`investigation-contexts/${caseRecord.fine_record_id}`,{case_id:caseRecord.id}),false,{refreshKey:refreshVersion});
  const history=useRead(domainPath(`investigation-cases/${caseRecord.id}/findings`,{page,page_size:20}),true,{refreshKey:refreshVersion});
  const ctx=context.data;
  const caseContext=ctx?.case_context?.find(item => item.case.id===caseRecord.id);
  const latestId=caseContext?.latest_finding?.id;
  const findingId=selectedId || latestId || (history.data?.items?.length ? history.data.items.at(-1).id : '');
  const finding=useRead(findingId ? domainPath(`findings/${findingId}`) : null,false,{refreshKey:refreshVersion});
  const current=finding.data?.id===latestId;
  // A handed-off case has no stored Finding for this run; its assessment is on the handoff record.
  const handedOff=caseRecord.status==='handed_off' && !!caseRecord.handoff;
  function refreshAll() {refreshCase();}
  function select(id) {setSelectedId(id);setTab('Agent Finding');}
  return <><div className="records-head"><div><h2>{caseRecord.summary ? `${caseRecord.summary.external_fine_id || 'Fine'} · ${caseRecord.summary.po_number} line ${caseRecord.summary.line_number} · ${caseRecord.summary.supplier_name}` : 'Case'}</h2><p className="record-id">{caseRecord.id}</p><div className="tinyrow"><Status value={caseRecord.status}/><span>{pretty(caseRecord.origin)}</span><Link className="link" to={`/fines/${caseRecord.fine_record_id}`}>Fine Record: {caseRecord.fine_record_id}</Link></div><p>Created <Timestamp value={caseRecord.created_at}/></p></div></div>
    {caseRecord.status==='handed_off' && <section className="note"><h2>Manual attention required</h2><p>{caseRecord.handoff?.reason || 'No recorded handoff reason is available.'}</p>{caseRecord.handoff && <><Timestamp value={caseRecord.handoff.occurred_at}/><p><button className="btn small" onClick={() => setTab('Agent Finding')}>See what the Agent checked</button></p></>}<ManualResolution caseRecord={caseRecord} onDone={stored => {refreshCase();if(stored)setTab('Outcome & Approval');}}/></section>}
    <div className="case-layout"><section className="card"><nav className="tabs" aria-label="Case sections">{['Overview','Agent Finding','Evidence','Outcome & Approval','History'].map(label => <button key={label} className={`tab ${tab===label?'selected':''}`} aria-pressed={tab===label} onClick={() => setTab(label)}>{label}</button>)}</nav><div className="inner">
      {tab==='Overview' && <><h2>Case overview</h2><p>Current lifecycle state: <strong>{pretty(caseRecord.status)}</strong>. Agent assessments are separate from financial calculations and human decisions.</p><ReadState resource={context}>{ctx && <dl className="fine-fields"><div><dt>Purchase order</dt><dd>{ctx.purchase_order?.po_number || 'Not supplied'}</dd></div><div><dt>PO line</dt><dd>{ctx.po_line?.line_number ?? 'Not supplied'} · {ctx.po_line?.item_description || ctx.po_line?.item_number || 'No item description'}</dd></div><div><dt>Supplier</dt><dd>{ctx.supplier?.name || 'Not supplied'}</dd></div><div><dt>Distribution center</dt><dd>{ctx.distribution_center?.name || 'Not supplied'}</dd></div><div><dt>Must arrive by</dt><dd>{ctx.po_line?.mabd || 'Not supplied'}</dd></div><div><dt>Fine metric</dt><dd>{pretty(ctx.fine_record?.metric)}</dd></div></dl>}</ReadState><button className="btn" onClick={()=>setTab('Outcome & Approval')}>Review calculated outcome</button></>}
      {['Agent Finding','Evidence'].includes(tab) && handedOff && <><h2>{tab}</h2><HandoffAssessment handoff={caseRecord.handoff} context={ctx} evidence={tab==='Evidence'}/><ReadState resource={context}/></>}
      {['Agent Finding','Evidence'].includes(tab) && !handedOff && <><h2>{tab}</h2>{findingId ? <><p className="badge gray">{latestId ? current?'Current Finding':'Historical Finding — not the current conclusion':'Finding version — currentness not confirmed'}</p><ReadState resource={finding}>{finding.data && <><p>Version {finding.data.version_number} · <Timestamp value={finding.data.created_at}/></p>{tab==='Agent Finding' ? <Finding finding={finding.data}/> : <Evidence key={finding.data.id} finding={finding.data} context={ctx} caseContext={caseContext}/>}</>}</ReadState></> : <><ReadState resource={history}/>{!history.loading && !history.error && <EmptyState title="No Finding available">The Agent has not submitted a Finding for this view.</EmptyState>}</>}
        <ReadState resource={context}/>{tab==='Agent Finding' && finding.data && <button className="btn" onClick={() => setTab('Evidence')}>Inspect cited evidence</button>}</>}
      {tab==='Outcome & Approval' && <OutcomeReview caseRecord={caseRecord} refreshVersion={refreshVersion} onRefresh={refreshCase} metric={ctx?.fine_record?.metric}/>}
      {tab==='History' && <><h2>Available Finding history</h2><p>This is available record history, not a complete Case audit timeline.</p><ReadState resource={history} empty="No Finding versions">{history.data && <>{history.data.items.map(item => <div className="step" key={item.id}><div><strong>Finding v{item.version_number}</strong><p>{item.summary || 'No summary'} · <Timestamp value={item.created_at}/></p><span>{item.id===latestId?'Current Finding':'Stored Finding version'}</span><button className="btn small" onClick={() => select(item.id)}>Read version {item.version_number}</button></div></div>)}<Pagination data={history.data} onPage={setPage}/></>}</ReadState></>}
    </div></section><aside><AgentPanel caseRecord={caseRecord} suggestedRunId={caseRecord.handoff?.agent_run_id || finding.data?.agent_run_id} onComplete={refreshAll}/></aside></div>
  </>;
}
export default function CaseWorkspace() {
  const {caseId}=useParams();
  const resource=useRead(isUUID(caseId)?domainPath(`investigation-cases/${caseId}`):null,false,{keepPrevious:true});
  return <><Link className="crumb-back" to="/cases">← Back to Investigations</Link><PageHead title="Case Workspace" subtitle="Operational context, Agent assessment, and cited evidence." refresh={resource.refresh}/>
    {!isUUID(caseId) ? <ErrorState message="Invalid Case ID. Expected a UUID."/> : resource.data ? <>
      {resource.loading && <Loading message="Refreshing Case details…"/>}
      {resource.error && <ErrorState message={`Unable to refresh Case details. Showing the last loaded record. ${resource.error.message}`} onRetry={resource.refresh}/>}
      {isUUID(resource.data.fine_record_id) && resource.data.id===caseId ? <WorkspaceBody key={caseId} caseRecord={resource.data} refreshCase={resource.refresh} refreshVersion={resource.revision}/> : <ErrorState message="The service returned an invalid Case response."/>}
    </> : <ReadState resource={resource}/>}

  </>;
}
