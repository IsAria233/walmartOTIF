import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {createMemoryRouter, RouterProvider} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import App from '../App';
import {AuthProvider} from '../auth/AuthContext';
const id=n=>`${String(n).padStart(8,'0')}-1111-4111-8111-111111111111`;
const c=id(1),f=id(2),e=id(3),o=id(4),l=id(5),a=id(6),m=id(7),r=id(8),fine=id(9);
const stamp='2026-11-20T12:00:00Z';
const json=(data,status=200)=>new Response(JSON.stringify(data),{status});
const page=items=>({items,page:1,page_size:100,total:items.length,total_pages:items.length?1:0});
const evaluation={id:e,investigation_case_id:c,finding_id:f,version_number:3,policy_version:'0.1',evaluated_at:stamp,result:{lines:[{cause_code:'C2',accountable_party:'walmart',disposition:'waive',original_amount:'777.00',corrected_amount:'0.00',reversal_amount:'777.00'}]},calculation_inputs:{non_compliant_cases:100,case_cost:'259.00',policy_fine_rate:'0.03'},calculation_outputs:{lines:[]}};
const finding={id:f,investigation_case_id:c,version_number:2,agent_run_id:r,cause_code:'C2',summary:'DC changed the appointment.',confidence:null,confidence_level:'high',ruled_out_causes:[],handoff_required:false,handoff_reason:null,injection_detected:false,created_at:stamp,facts:[]};
function setup({role='dispute_associate',manager=false,requireManager=false,status='awaiting_approval',historical=false,noRun=false,extraLine=false,override=()=>null,path}={}) {
 const userId=crypto.randomUUID();const token=`h.${btoa(JSON.stringify({exp:Math.floor(Date.now()/1000)+1800}))}.s`;
 const state={case:{id:c,fine_record_id:fine,status,origin:'supplier_dispute',created_at:stamp,handoff:null},outcome:{id:o,investigation_case_id:c,evaluation_id:e,status:manager?'pending_manager_approval':'pending_approval',created_at:stamp},line:{id:l,case_outcome_id:o,investigation_case_id:c,evaluated_line_key:fine,finding_id:f,outcome:'waive',policy_version:'0.1',accountable_party:'walmart',original_amount:'777.00',corrected_amount:'0.00',reversal_amount:'777.00',rationale:'Persisted rules result',calculated_at:stamp,approval_status:manager?'pending_manager_approval':'pending_approval',created_at:stamp},rows:[],resumeCalls:0};
 function approval(ident,type,status){return {approval:{id:ident,assigned_to_user_id:null,line_outcome_id:l,approval_type:type,status,created_at:stamp},decisions:status==='approved'?[{id:id(30),approval_id:ident,auth_user_id:id(31),decision:'approved',decided_at:stamp,comment:'Associate checked records'}]:[]};}
 state.rows=[approval(a,'associate',manager?'approved':'pending')];if(manager)state.rows.push(approval(m,'manager','pending'));
 const fetcher=vi.fn((path,options)=>{
  if(path==='/api/auth/login')return Promise.resolve(json({access_token:token,token_type:'bearer'}));
  if(path==='/api/auth/me')return Promise.resolve(json({user_id:userId,role}));
  const url=new URL(path,'http://local');const replacement=override(url,options,state);if(replacement)return Promise.resolve(replacement);
  const item={outcome:state.outcome,line_outcomes:[state.line,...(extraLine?[{...state.line,id:id(40),evaluated_line_key:id(41),approval_status:'approved'}]:[])]};
  if(url.pathname===`/api/domain/v1/investigation-cases/${c}`)return Promise.resolve(json(state.case));
  if(url.pathname==='/api/domain/v1/investigation-cases')return Promise.resolve(json(page([state.case])));
  if(url.pathname.startsWith('/api/domain/v1/investigation-contexts/'))return Promise.resolve(json({fine_record:{metric:'on_time'},purchase_order:{po_number:'TEST-PO'},po_line:{},supplier:{},distribution_center:{},case_context:[{case:state.case,latest_finding:finding,outcomes:[{outcome:state.outcome,line_outcomes:[{line_outcome:state.line,approvals:state.rows}]}]}]}));
  if(url.pathname.endsWith('/findings'))return Promise.resolve(json(page([finding])));
  if(url.pathname===`/api/domain/v1/findings/${f}`)return Promise.resolve(json({...finding,agent_run_id:noRun?null:r}));
  if(url.pathname.endsWith('/evaluations'))return Promise.resolve(json(page([evaluation])));
  if(url.pathname===`/api/domain/v1/evaluations/${e}`)return Promise.resolve(json(evaluation));
  if(url.pathname.endsWith('/outcome'))return Promise.resolve(json(page(historical?[{...item,outcome:{...state.outcome,id:id(50)},line_outcomes:[]},item]:[item])));
  if(url.pathname===`/api/domain/v1/outcomes/${o}/approvals`){
   if(options.method==='POST'){
    const body=JSON.parse(options.body);const row=state.rows.find(item=>item.approval.approval_type===body.stage);row.approval.status=body.decision;
    const record={id:crypto.randomUUID(),approval_id:row.approval.id,auth_user_id:userId,decision:body.decision,decided_at:stamp,comment:body.comment};row.decisions.push(record);
    if(body.decision==='rejected'){state.line.approval_status='rejected';state.outcome.status='rejected';state.case.status='revision_required';}
    else if(body.stage==='associate' && requireManager){state.rows.push(approval(m,'manager','pending'));state.line.approval_status='pending_manager_approval';state.outcome.status='pending_manager_approval';}
    else{state.line.approval_status='approved';state.outcome.status='approved';state.case.status='closed';}
    return Promise.resolve(json(record,201));
   }return Promise.resolve(json(page(state.rows)));
  }
  if(url.pathname.startsWith('/api/agent/investigations/')){
   const resume=url.pathname.endsWith('/resume');if(resume)state.resumeCalls++;
   return Promise.resolve(json({run_id:r,case_id:c,status:resume?state.outcome.status:'awaiting_approval',approval_status:state.outcome.status,paused_for_approval:!resume,unfinished:false,findings:null,domain:{outcome_id:o,finding_id:f},tool_log:[],model_steps:3,trace_id:null,handoff_reason:null,fine_type:'on_time'}));
  }
  return Promise.resolve(json(page([])));
 });
 vi.stubGlobal('fetch',fetcher);const router=createMemoryRouter([{path:'*',element:<AuthProvider><App/></AuthProvider>}],{initialEntries:[path||`/cases/${c}`]});render(<RouterProvider router={router}/>);return {fetcher,state,router,token,userId};
}
async function login(open=true){fireEvent.change(screen.getByLabelText('Username'),{target:{value:'reviewer'}});fireEvent.change(screen.getByLabelText('Password'),{target:{value:'password'}});fireEvent.submit(screen.getByRole('form',{name:'Sign in'}));await screen.findByRole('navigation',{name:'Workspace'});if(open){await screen.findByRole('button',{name:'Outcome & Approval',exact:true});await userEvent.click(screen.getByRole('button',{name:'Outcome & Approval',exact:true}));await screen.findByText('Evaluation version: 3 · Policy: 0.1');}}
const writes=fetcher=>fetcher.mock.calls.filter(([url,options])=>url===`/api/domain/v1/outcomes/${o}/approvals`&&options.method==='POST');
async function confirm(choice='approve',reason){await userEvent.click(await screen.findByRole('button',{name:choice==='approve'?'Approve line':'Reject line'}));if(reason)fireEvent.change(screen.getByLabelText('Decision comment'),{target:{value:reason}});fireEvent.click(screen.getByRole('button',{name:`Confirm ${choice}`}));}
afterEach(()=>vi.unstubAllGlobals());
it('maps Evaluation/Outcome relationships and persisted monetary values per line',async()=>{
 setup({extraLine:true});await login();expect(screen.getAllByText('$777.00')).toHaveLength(4);expect(screen.getAllByText('$0.00')).toHaveLength(2);expect(screen.getByText(`Evaluation: ${e} · Finding: ${f}`)).toBeInTheDocument();expect(await screen.findByText('Related Agent cause: C2 (assessment, not human approval).')).toBeInTheDocument();expect(screen.getAllByRole('heading',{name:/Line Outcome/})).toHaveLength(2);expect(screen.getByText('Pending stage:')).toHaveTextContent('Associate');
});
it('records Associate approval with JWT, refreshes Domain first, then resumes exact Run',async()=>{
 const {fetcher,token,state}=setup();await login();await confirm();await screen.findByText(/Agent Run status: approved/);expect(writes(fetcher)).toHaveLength(1);const write=writes(fetcher)[0];expect(write[1].headers.Authorization).toBe(`Bearer ${token}`);expect(JSON.parse(write[1].body)).toEqual({line_outcome_id:l,stage:'associate',decision:'approved',comment:null});
 const postIndex=fetcher.mock.calls.indexOf(write);const resumeIndex=fetcher.mock.calls.findIndex(([url])=>url.endsWith('/resume'));expect(resumeIndex).toBeGreaterThan(postIndex);expect(fetcher.mock.calls.slice(postIndex+1,resumeIndex).some(([url])=>url===`/api/domain/v1/investigation-cases/${c}`)).toBe(true);expect(state.resumeCalls).toBe(1);expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();
});
it.each([false,true])('requires a reason for %s Manager rejection and records it',async manager=>{
 const {fetcher}=setup({manager,role:manager?'compliance_manager':'dispute_associate'});await login();await userEvent.click(await screen.findByRole('button',{name:'Reject line'}));const form=screen.getByRole('form',{name:`Confirm decision ${l}`});fireEvent.submit(form);expect(await screen.findByRole('alert')).toHaveTextContent('rejection reason');expect(writes(fetcher)).toHaveLength(0);fireEvent.change(screen.getByLabelText('Decision comment'),{target:{value:'Evidence is incomplete'}});fireEvent.submit(form);await screen.findByText(/Agent Run status: rejected/);expect(JSON.parse(writes(fetcher)[0][1].body)).toMatchObject({stage:manager?'manager':'associate',decision:'rejected',comment:'Evidence is incomplete'});
});
it('uses the pending Manager stage and displays previous Associate decisions',async()=>{
 const {fetcher}=setup({role:'compliance_manager',manager:true});await login();await screen.findByText('Associate checked records');await confirm();await screen.findByText(/Agent Run status: approved/);expect(JSON.parse(writes(fetcher)[0][1].body).stage).toBe('manager');
});
it('allows a Manager to decide successive Associate and Manager stages without threshold logic',async()=>{
 const {fetcher}=setup({role:'compliance_manager',requireManager:true});await login();await confirm();await screen.findByText(/Agent Run status: pending_manager_approval/);await confirm();await screen.findByText(/Agent Run status: approved/);expect(writes(fetcher).map(([,options])=>JSON.parse(options.body).stage)).toEqual(['associate','manager']);
});
it.each([['admin',false],['admin',true],['dispute_associate',true]])('hides %s controls for manager=%s',async(role,manager)=>{
 setup({role,manager});await login();await screen.findByText(/Your role cannot decide/);expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Reject line'})).not.toBeInTheDocument();
});
it('keeps historical pending Outcomes read-only',async()=>{
 setup({historical:true});await login();fireEvent.change(screen.getByLabelText('Outcome version'),{target:{value:o}});await screen.findByText('Historical Outcome — read-only.');expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();
});
it('does not expose controls for closed Cases or finalized stages',async()=>{
 setup({status:'closed'});await login();await screen.findByText(/Line approval state/);expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();
});
it('prevents duplicate writes during a pending request',async()=>{
 let finish;const {fetcher,userId}=setup({override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'?new Promise(resolve=>{finish=resolve;}):null});await login();await confirm();await waitFor(()=>expect(writes(fetcher)).toHaveLength(1));expect(screen.getByText(/Saving decision or reconciling/)).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Confirm approve'})).not.toBeInTheDocument();
 await act(async()=>finish(json({id:id(70),approval_id:a,auth_user_id:userId,decision:'approved',decided_at:stamp,comment:null},201)));await screen.findByText(/Agent Run status:/);expect(writes(fetcher)).toHaveLength(1);
});
it.each([403,409])('blocks resubmission after Domain %s and offers reconciliation',async status=>{
 const {fetcher}=setup({override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'?json({error:{message:`Decision ${status}`}},status):null});await login();await confirm();expect(await screen.findByRole('alert')).toHaveTextContent(`Decision ${status}`);expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'Check decision state'}));expect(await screen.findByRole('alert')).toHaveTextContent('No completed decision');expect(writes(fetcher)).toHaveLength(1);
});
it('clears authentication on a Domain decision 401',async()=>{
 const {fetcher}=setup({override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'?json({error:{message:'Expired'}},401):null});await login();await confirm();expect(await screen.findByRole('heading',{name:'Welcome back'})).toBeInTheDocument();expect(writes(fetcher)).toHaveLength(1);
});
it('detects stale pending state in preflight without writing',async()=>{
 let reads=0;const {fetcher}=setup({override:url=>url.pathname===`/api/domain/v1/investigation-cases/${c}`&&++reads>1?json({id:c,status:'closed'}):null});await login();await confirm();expect(await screen.findByRole('alert')).toHaveTextContent('approval state changed');expect(writes(fetcher)).toHaveLength(0);
});
it('keeps a successful decision separate from failed resume and retries only resume',async()=>{
 let resumes=0;const {fetcher}=setup({override:url=>url.pathname.endsWith('/resume')&&++resumes===1?json({detail:'Checkpoint unavailable'},503):null});await login();await confirm();expect(await screen.findByRole('alert')).toHaveTextContent('Domain decision recorded; follow-up failed');await userEvent.click(screen.getByRole('button',{name:'Retry Agent resume'}));await screen.findByText(/Agent Run status: approved/);expect(writes(fetcher)).toHaveLength(1);expect(resumes).toBe(2);
});
it('reports missing Run IDs instead of guessing',async()=>{
 const {fetcher}=setup({noRun:true});await login();await confirm();await screen.findByText(/No Agent Run ID is available/);expect(fetcher.mock.calls.some(([url])=>url.endsWith('/resume'))).toBe(false);expect(writes(fetcher)).toHaveLength(1);
});
it('refuses to resume an unrelated Run',async()=>{
 const {fetcher}=setup({override:url=>url.pathname===`/api/agent/investigations/${r}`?json({run_id:r,case_id:c,status:'awaiting_approval',paused_for_approval:true,domain:{outcome_id:id(90),finding_id:f}}):null});await login();await confirm();expect(await screen.findByRole('alert')).toHaveTextContent('does not match this Outcome');expect(fetcher.mock.calls.some(([url])=>url.endsWith('/resume'))).toBe(false);
});
it('blocks an uncertain network write across tab navigation without retrying it',async()=>{
 const {fetcher}=setup({override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'?Promise.reject(new TypeError('Network')):null});await login();await confirm();await screen.findByText('Decision result is uncertain. Approval resubmission is blocked.');await userEvent.click(screen.getByRole('button',{name:'Overview',exact:true}));await userEvent.click(screen.getByRole('button',{name:'Outcome & Approval',exact:true}));await screen.findByText('Decision result is uncertain. Approval resubmission is blocked.');expect(writes(fetcher)).toHaveLength(1);
});
it('renders empty Outcomes and handles load errors with retry',async()=>{
 let reads=0;setup({override:url=>url.pathname.endsWith('/outcome')?++reads===1?json({detail:'Outcomes unavailable'},503):json(page([])):null});await login(false);await userEvent.click(await screen.findByRole('button',{name:'Outcome & Approval',exact:true}));expect(await screen.findByRole('alert')).toHaveTextContent('Outcomes unavailable');await userEvent.click(screen.getByRole('button',{name:'Try again'}));expect(await screen.findByText('No Outcome available.')).toBeInTheDocument();
});
it('shows Manager entry and actual pending stage from existing Case context',async()=>{
 const {router}=setup({role:'compliance_manager',manager:true,path:'/manager-review'});await login(false);await userEvent.click(await screen.findByRole('link',{name:c}));expect(router.state.location.pathname).toBe(`/cases/${c}`);
});
it('guards the Manager entry route for non-Managers',async()=>{
 setup({role:'dispute_associate',path:'/manager-review'});await login(false);expect(await screen.findByRole('heading',{name:'Access restricted'})).toBeInTheDocument();expect(screen.queryByRole('link',{name:'Manager Review'})).not.toBeInTheDocument();
});
it('treats an invalid success DTO as an uncertain write rather than resuming',async()=>{
 const {fetcher}=setup({override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'?json({id:id(60),approval_id:id(61),decision:'approved'},201):null});await login();await confirm();expect(await screen.findByRole('alert')).toHaveTextContent('unconfirmed decision response');expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();expect(fetcher.mock.calls.some(([url])=>url.endsWith('/resume'))).toBe(false);
});
it('loads approval history beyond page 1 before offering Manager actions',async()=>{
 setup({manager:true,role:'compliance_manager',override:(url,options,state)=>url.pathname.endsWith('/approvals')&&options.method==='GET'?json({items:[state.rows[url.searchParams.get('page')==='2'?1:0]],page:Number(url.searchParams.get('page')),page_size:100,total:101,total_pages:2}):null});await login();await screen.findByRole('button',{name:'Approve line'});expect(screen.getByText('Pending stage:')).toHaveTextContent('Manager');expect(screen.getByText('Associate checked records')).toBeInTheDocument();
});
it('reconciles an uncertain but recorded Associate decision without blocking the next Manager stage',async()=>{
 let uncertain=true;const {fetcher,state}=setup({role:'compliance_manager',requireManager:true,override:(url,options)=>url.pathname.endsWith('/approvals')&&options.method==='POST'&&uncertain?Promise.reject(new TypeError('Network')):null});await login();await confirm();await screen.findByRole('button',{name:'Check decision state'});
 state.rows[0].approval.status='approved';state.rows[0].decisions=[{id:id(80),approval_id:a,auth_user_id:id(81),decision:'approved',decided_at:stamp,comment:'Committed before disconnect'}];state.rows.push({approval:{id:m,line_outcome_id:l,assigned_to_user_id:null,approval_type:'manager',status:'pending',created_at:stamp},decisions:[]});state.line.approval_status='pending_manager_approval';state.outcome.status='pending_manager_approval';
 await userEvent.click(screen.getByRole('button',{name:'Refresh authoritative state'}));await screen.findByText('Committed before disconnect');await userEvent.click(screen.getByRole('button',{name:'Check decision state'}));await userEvent.click(await screen.findByRole('button',{name:'Retry Agent resume'}));await screen.findByText(/Agent Run status: pending_manager_approval/);
 uncertain=false;await confirm();await screen.findByText(/Agent Run status: approved/);expect(writes(fetcher)).toHaveLength(2);expect(JSON.parse(writes(fetcher)[1][1].body).stage).toBe('manager');
});
it('keeps approval submission blocked when post-decision Domain refresh fails, then recovers resume alone',async()=>{
 let afterWrite=false;let failRefresh=true;const {fetcher}=setup({override:(url,options)=>{
  if(url.pathname.endsWith('/approvals')&&options.method==='POST')afterWrite=true;
  if(afterWrite && failRefresh && url.pathname===`/api/domain/v1/investigation-cases/${c}`)return json({detail:'Refresh offline'},503);
  return null;
 }});await login();await confirm();expect(await screen.findByText(/Domain decision recorded; follow-up failed/)).toBeInTheDocument();failRefresh=false;await userEvent.click(screen.getByRole('button',{name:'Retry Agent resume'}));await screen.findByText(/Agent Run status: approved/);expect(writes(fetcher)).toHaveLength(1);
});
it('uses persisted Manager stages even when the reversal amount is small',async()=>{
 const {state}=setup({manager:true,role:'compliance_manager'});state.line.reversal_amount='1.00';state.line.original_amount='1.00';await login();expect(await screen.findByRole('button',{name:'Approve line'})).toBeEnabled();expect(screen.getByText('Pending stage:')).toHaveTextContent('Manager');
});
it('keeps finalized approval records read-only even on an awaiting-approval Case',async()=>{
 const {state}=setup();state.line.approval_status='approved';state.outcome.status='approved';state.rows[0].approval.status='approved';state.rows[0].decisions=[{id:id(90),approval_id:a,auth_user_id:id(91),decision:'approved',decided_at:stamp,comment:'Already completed'}];await login();await screen.findByText('Already completed');expect(screen.queryByRole('button',{name:'Approve line'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Reject line'})).not.toBeInTheDocument();
});
