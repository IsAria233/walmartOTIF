import {useState} from 'react';
import {Link} from 'react-router-dom';
import useRead from '../hooks/useRead';
import {domainPath} from '../api/domain';
import {Money, PageHead, Pagination, ReadState} from '../components/Records';
function Candidate({record}) {
  const context=useRead(domainPath(`investigation-contexts/${record.fine_record_id}`,{case_id:record.id}),false);
  const item=context.data?.case_context?.find(item=>item.case.id===record.id);
  const current=item?.outcomes?.[0];
  const lines=current?.line_outcomes.filter(({line_outcome,approvals})=>line_outcome.approval_status==='pending_manager_approval' && approvals.some(({approval,decisions})=>approval.approval_type==='manager'&&approval.status==='pending'&&!decisions.length) && approvals.some(({approval})=>approval.approval_type==='associate'&&approval.status==='approved')) || [];
  return <ReadState resource={context}>{context.data && <div className="step"><div><Link className="link record-id" to={`/cases/${record.id}`}>{record.id}</Link>{lines.length?lines.map(({line_outcome})=><p key={line_outcome.id}>Manager review pending · {line_outcome.evaluated_line_key} · Reversal <Money value={line_outcome.reversal_amount}/></p>):<p>No pending Manager stage in the loaded current Outcome.</p>}</div></div>}</ReadState>;
}
export default function ManagerReview() {
  const [page,setPage]=useState(1);
  const resource=useRead(domainPath('investigation-cases',{status:'awaiting_approval',page,page_size:20,sort_by:'created_at',sort_order:'desc'}));
  return <><PageHead title="Manager Review" subtitle="Inspect persisted Manager stages in awaiting-approval Cases." refresh={resource.refresh}/><section className="card inner"><p>This is a page of candidate Cases, not a dedicated Manager inbox. Counts include all awaiting-approval Cases. Open a Case’s Outcome & Approval section to review the latest stage and Associate decisions.</p><ReadState resource={resource} empty="No awaiting-approval Cases">{resource.data && <>{resource.data.items.map(record=><Candidate key={`${record.id}:${resource.revision}`} record={record}/>)}<Pagination data={resource.data} onPage={setPage}/></>}</ReadState></section></>;
}
