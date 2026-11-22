import {domainPath, validatePage} from './domain';
import {validateRun} from './agent';
export const STAGE_ROLES={associate:['dispute_associate','compliance_manager'],manager:['compliance_manager']};
export async function allPages(client,path) {
  const items=[];let page=1;let totalPages=1;
  do {
    const url=new URL(path,'http://local');url.searchParams.set('page',page);url.searchParams.set('page_size',100);
    const data=validatePage(await client(url.pathname+url.search));
    items.push(...data.items);totalPages=data.total_pages;page++;
  } while(page<=totalPages);
  return items;
}
export function pendingStage(line,approvals) {
  const pending=approvals.filter(item=>item.approval.line_outcome_id===line.id && item.approval.status==='pending' && !item.decisions.length);
  const expected=line.approval_status==='pending_manager_approval'?'manager':line.approval_status==='pending_approval'?'associate':null;
  const stage=pending.find(item=>item.approval.approval_type===expected);
  if(expected==='manager' && !approvals.some(item=>item.approval.line_outcome_id===line.id && item.approval.approval_type==='associate' && item.approval.status==='approved'))return null;
  return stage || null;
}
export async function preflight(client,caseId,outcomeId,lineId,approvalId,role) {
  const [record,outcomes,approvals]=await Promise.all([
    client(domainPath(`investigation-cases/${caseId}`)),
    client(domainPath(`investigation-cases/${caseId}/outcome`,{page:1,page_size:20})),
    allPages(client,domainPath(`outcomes/${outcomeId}/approvals`)),
  ]);
  const current=validatePage(outcomes).items[0];
  const line=current?.line_outcomes.find(item=>item.id===lineId);
  const stage=line && pendingStage(line,approvals);
  if(record.status!=='awaiting_approval' || current?.outcome.id!==outcomeId || !['pending_approval','pending_manager_approval'].includes(current.outcome.status) || stage?.approval.id!==approvalId || !STAGE_ROLES[stage.approval.approval_type]?.includes(role))throw new Error('The approval state changed. Refresh authoritative state before reviewing again.');
  return stage.approval.approval_type;
}
export async function resumeDecision(client,caseId,outcomeId,findingId) {
  // Validate the exact persisted Finding -> Run -> Outcome relationship.
  const finding=await client(domainPath(`findings/${findingId}`));
  if(finding.investigation_case_id!==caseId || finding.id!==findingId)throw new Error('Finding does not belong to this Case. Agent was not resumed.');
  if(!finding.agent_run_id)return 'Decision recorded. No Agent Run ID is available for this Finding; resume is unavailable.';
  const path=`/api/agent/investigations/${finding.agent_run_id}`;
  const run=validateRun(await client(path),caseId);
  if(run.run_id!==finding.agent_run_id || run.domain?.outcome_id!==outcomeId || run.domain?.finding_id!==findingId)throw new Error('The known Run does not match this Outcome and Finding. Agent was not resumed.');
  if(!run.paused_for_approval)return `Decision recorded. Agent Run is ${run.status}; no approval pause to resume.`;
  const resumed=validateRun(await client(`${path}/resume`,{method:'POST'}),caseId);
  if(resumed.run_id!==run.run_id)throw new Error('Agent returned a different Run after resume.');
  return `Decision recorded. Agent Run status: ${resumed.status}${resumed.approval_status?` (${resumed.approval_status})`:''}.`;
}
const recovery=new Map();
export function recoveryRead(scope) {try{return JSON.parse(sessionStorage.getItem(`otif-decision:${scope}`)) || recovery.get(scope) || null;}catch{return recovery.get(scope)||null;}}
export function recoverySave(scope,value) {recovery.set(scope,value);try{sessionStorage.setItem(`otif-decision:${scope}`,JSON.stringify(value));}catch{/* Memory fallback. */}}
