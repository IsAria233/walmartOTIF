import {act, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {createMemoryRouter, RouterProvider} from 'react-router-dom';
import {afterEach, expect, it, vi} from 'vitest';
import App from '../App';
import {AuthProvider} from '../auth/AuthContext';

const fineId='11111111-1111-4111-8111-111111111111';
const caseId='22222222-2222-4222-8222-222222222222';
const supplierId='33333333-3333-4333-8333-333333333333';
const otherId='44444444-4444-4444-8444-444444444444';
const caseRecord={id:caseId,fine_record_id:fineId,status:'awaiting_approval',origin:'supplier_dispute',created_at:'2026-11-20T12:30:00Z'};
const fine={id:fineId,external_fine_id:'TEST-FINE-101',po_line_id:otherId,po_line_version_id:null,po_version_used:2,ordered_cases:100,received_cases:80,non_compliant_cases:20,system_accountability:'supplier',metric:'in_full',original_amount:'120.00',case_cost_snapshot:'200.00',fine_rate:'0.03',recorded_arrival_ts:null,status:'recorded',created_at:'2026-11-20T12:00:00Z'};
const dispute={id:otherId,supplier_id:supplierId,external_dispute_id:'TEST-DISPUTE-01',submitted_at:'2026-11-21T12:00:00Z',reason_category:'quantity',reason_text:'Supplier claims a receiving discrepancy.',amount_disputed:'90.00',status:'submitted'};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status});
const page=(items=[],number=1,total=items.length,size=20)=>({items,page:number,page_size:size,total,total_pages:Math.ceil(total/size)});
const casesPath='/api/domain/v1/investigation-cases';
const finesPath='/api/domain/v1/fine-records';
function setup(path='/cases',handler=()=>json(page())) {
  const token=`header.${btoa(JSON.stringify({exp:Math.floor(Date.now()/1000)+1800}))}.sig`;
  const fetcher=vi.fn((url,options)=>{
    if(url==='/api/auth/login')return Promise.resolve(json({access_token:token,token_type:'bearer'}));
    if(url==='/api/auth/me')return Promise.resolve(json({user_id:supplierId,role:'dispute_associate'}));
    return Promise.resolve(handler(new URL(url,'http://localhost'),options));
  });
  vi.stubGlobal('fetch',fetcher);
  const router=createMemoryRouter([{path:'*',element:<AuthProvider><App/></AuthProvider>}],{initialEntries:[path]});
  render(<RouterProvider router={router}/>);
  return {router,fetcher,token};
}
async function login() {
  fireEvent.change(screen.getByLabelText('Username'),{target:{value:'test_user'}});
  fireEvent.change(screen.getByLabelText('Password'),{target:{value:'test_password'}});
  fireEvent.submit(screen.getByRole('form',{name:'Sign in'}));
  await screen.findByRole('navigation');
}
function requestParams(fetcher) {return fetcher.mock.calls.filter(([url])=>url.startsWith(casesPath)).map(([url])=>new URL(url,'http://localhost').searchParams);}
afterEach(()=>vi.unstubAllGlobals());

it('maps queue DTOs without invented fields and links to the case placeholder',async()=>{
  const summary={external_fine_id:'FINE-1001',metric:'in_full',original_amount:'216.00',po_number:'PO-77',line_number:2,supplier_name:'Cedar Fork Supply'};
  const {fetcher,token,router}=setup('/cases',()=>json(page([{...caseRecord,summary}])));await login();
  const table=await screen.findByRole('table',{name:'Investigation cases'});
  // A reviewer recognises a case by its fine, PO line and supplier; the UUID is secondary.
  for (const text of ['FINE-1001','PO-77 · line 2','Cedar Fork Supply','In full','$216.00',caseRecord.id]) expect(table).toHaveTextContent(text);
  expect(within(table).getByRole('link',{name:'FINE-1001'})).toHaveAttribute('href',`/cases/${caseRecord.id}`);expect(within(table).getByRole('link',{name:'Fine record'})).toHaveAttribute('href',`/fines/${fineId}`);
  expect(table).toHaveTextContent('Supplier dispute');expect(table).toHaveTextContent('Awaiting approval');
  expect(table.querySelector('time')).toHaveAttribute('datetime',caseRecord.created_at);
  expect(within(table).queryByText('Supplier & PO')).not.toBeInTheDocument();
  const call=fetcher.mock.calls.find(([url])=>url.startsWith(casesPath));expect(call[1].headers.Authorization).toBe(`Bearer ${token}`);expect(call[1].method).toBe('GET');
  await userEvent.click(within(table).getByRole('link',{name:'FINE-1001'}));
  expect(router.state.location.pathname).toBe(`/cases/${caseId}`);expect(screen.getByRole('heading',{level:1,name:'Case Workspace'})).toBeInTheDocument();
});
it('sends all supported queue filters as server parameters and clears them',async()=>{
  const {fetcher}=setup('/cases?page=3',()=>json(page([caseRecord])));await login();await screen.findByRole('table');
  fireEvent.change(screen.getByLabelText('Status'),{target:{value:'handed_off'}});
  fireEvent.change(screen.getByLabelText('Origin / source'),{target:{value:'pre_invoice_scan'}});
  fireEvent.change(screen.getByLabelText('Fine Record ID'),{target:{value:fineId}});
  fireEvent.change(screen.getByLabelText('Supplier ID'),{target:{value:supplierId}});
  fireEvent.change(screen.getByLabelText('Created from (local time)'),{target:{value:'2026-11-19T12:00'}});
  fireEvent.change(screen.getByLabelText('Created to (local time)'),{target:{value:'2026-11-21T12:00'}});
  fireEvent.submit(screen.getByRole('form',{name:'Case filters'}));
  await waitFor(()=>expect(requestParams(fetcher).at(-1).get('status')).toBe('handed_off'));
  const query=requestParams(fetcher).at(-1);
  expect(Object.fromEntries(query)).toMatchObject({page:'1',status:'handed_off',origin:'pre_invoice_scan',fine_record_id:fineId,supplier_id:supplierId,created_from:new Date('2026-11-19T12:00').toISOString(),created_to:new Date('2026-11-21T12:00').toISOString()});
  await userEvent.click(screen.getByRole('button',{name:'Clear filters'}));
  await waitFor(()=>expect(requestParams(fetcher).at(-1).has('status')).toBe(false));
  expect(screen.getByLabelText('Fine Record ID')).toHaveValue('');
});
it('validates date order before requesting and uses source alias on a deep link',async()=>{
  const {fetcher}=setup('/cases?source=pre_invoice_scan',()=>json(page()));await login();await screen.findByText('No matching investigations');
  expect(requestParams(fetcher)[0].get('origin')).toBe('pre_invoice_scan');
  fireEvent.change(screen.getByLabelText('Sort by'),{target:{value:'origin'}});
  await waitFor(()=>expect(requestParams(fetcher).at(-1).get('sort_by')).toBe('origin'));
  expect(requestParams(fetcher).at(-1).get('origin')).toBe('pre_invoice_scan');
  const count=fetcher.mock.calls.length;
  fireEvent.change(screen.getByLabelText('Created from (local time)'),{target:{value:'2026-11-22T12:00'}});
  fireEvent.change(screen.getByLabelText('Created to (local time)'),{target:{value:'2026-11-21T12:00'}});
  fireEvent.submit(screen.getByRole('form',{name:'Case filters'}));
  expect(screen.getByRole('alert')).toHaveTextContent('Created from must be before');expect(fetcher).toHaveBeenCalledTimes(count);
});
it('uses API totals, pages, page size and supported sorting, resetting to page 1',async()=>{
  const {fetcher}=setup('/cases',url=>json(page([caseRecord],Number(url.searchParams.get('page')),41,Number(url.searchParams.get('page_size')))));await login();await screen.findByText('41 total · Page 1 of 3');
  await userEvent.click(screen.getByRole('button',{name:'Next'}));await screen.findByText('41 total · Page 2 of 3');
  expect(requestParams(fetcher).at(-1).get('page')).toBe('2');
  fireEvent.change(screen.getByLabelText('Sort by'),{target:{value:'status'}});await screen.findByText('41 total · Page 1 of 3');
  expect(requestParams(fetcher).at(-1).get('sort_by')).toBe('status');
  fireEvent.change(screen.getByLabelText('Sort order'),{target:{value:'asc'}});
  await waitFor(()=>expect(requestParams(fetcher).at(-1).get('sort_order')).toBe('asc'));
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'50'}});await screen.findByText('41 total · Page 1 of 1');
  expect(screen.getByRole('button',{name:'Next'})).toBeDisabled();
  expect(requestParams(fetcher).at(-1).get('page_size')).toBe('50');
});
it('shows loading, handles empty records, refreshes and retries an API error',async()=>{
  let finish;let calls=0;
  setup('/cases',()=>{calls++;if(calls===1)return new Promise(resolve=>{finish=resolve;});if(calls===2)return json({error:{message:'Database unavailable'}},503);return json(page([caseRecord]));});
  await login();expect(screen.getByText('Loading records…')).toBeInTheDocument();
  await act(async()=>finish(json(page())));expect(await screen.findByText('No matching investigations')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:'↻ Refresh'}));expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable');
  await userEvent.click(screen.getByRole('button',{name:'Try again'}));expect(await screen.findByRole('table')).toHaveTextContent(caseId);
});
it('ignores stale responses even when the transport does not honor abort',async()=>{
  let finish;let calls=0;const {fetcher}=setup('/cases',()=>{calls++;return calls===1?new Promise(resolve=>{finish=resolve;}):json(page([{...caseRecord,id:otherId}]));});await login();
  fireEvent.change(screen.getByLabelText('Sort by'),{target:{value:'origin'}});
  expect(await screen.findByRole('link',{name:otherId})).toBeInTheDocument();
  const first=fetcher.mock.calls.find(([url])=>url.startsWith(casesPath));expect(first[1].signal.aborted).toBe(true);
  await act(async()=>finish(json(page([caseRecord]))));expect(screen.queryByRole('link',{name:caseId})).not.toBeInTheDocument();expect(screen.getByRole('table')).toHaveTextContent(otherId);
});
it.each([401,403])('handles Domain %s without bypassing auth or showing data',async status=>{
  const {fetcher}=setup('/cases',()=>json({error:{message:status===401?'Session expired':'Review access denied'}},status));await login();
  if(status===401){expect(await screen.findByRole('heading',{name:'Welcome back'})).toBeInTheDocument();expect(screen.queryByRole('navigation')).not.toBeInTheDocument();}
  else {expect(await screen.findByRole('alert')).toHaveTextContent('Review access denied');expect(screen.getByRole('button',{name:'Sign out'})).toBeInTheDocument();}
  expect(fetcher.mock.calls.filter(([url])=>url==='/api/auth/login')).toHaveLength(1);
});
it('rejects malformed page envelopes with retry instead of rendering misleading totals',async()=>{
  setup('/cases',()=>json({items:[],total:99}));await login();expect(await screen.findByRole('alert')).toHaveTextContent('invalid page response');expect(screen.queryByText('99 results')).not.toBeInTheDocument();
});
it('maps fine list DTOs, paginates and navigates to a fine with related disputes and cases',async()=>{
  const {router,fetcher}=setup('/fines',url=>{
    if(url.pathname===finesPath)return json(page([fine],Number(url.searchParams.get('page')),21));
    if(url.pathname===`${finesPath}/${fineId}`)return json(fine);
    if(url.pathname.endsWith('/disputes'))return json(page([dispute]));
    return json(page([caseRecord]));
  });await login();const table=await screen.findByRole('table',{name:'Fine records'});expect(table).toHaveTextContent('$120.00');expect(table).toHaveTextContent(otherId);expect(table).toHaveTextContent('In full');
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button',{name:'Next'}));await screen.findByText('21 total · Page 2 of 2');
  expect(fetcher.mock.calls.some(([url])=>url===`${finesPath}?page=2&page_size=20`)).toBe(true);
  await userEvent.click(screen.getByRole('link',{name:'TEST-FINE-101'}));
  expect(router.state.location.pathname).toBe(`/fines/${fineId}`);
  await screen.findByRole('heading',{name:'Fine details'});
  expect(screen.getByText('Non-compliant cases').nextSibling).toHaveTextContent('20');
  expect(screen.getByText('PO version used').nextSibling).toHaveTextContent('2');
  expect(screen.getByText('Fine rate (fraction)').nextSibling).toHaveTextContent('0.03');
  expect(await screen.findByText(dispute.reason_text)).toBeInTheDocument();expect(screen.getByText('$90.00')).toBeInTheDocument();
  const query=requestParams(fetcher).at(-1);expect(query.get('fine_record_id')).toBe(fineId);
  await userEvent.click(screen.getByRole('link',{name:caseId}));expect(router.state.location.pathname).toBe(`/cases/${caseId}`);
});
it('handles fine-list empty and error states with retry',async()=>{
  let calls=0;setup('/fines',()=>++calls===1?json({detail:'Unavailable'},503):json(page()));await login();
  expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable');await userEvent.click(screen.getByRole('button',{name:'Try again'}));expect(await screen.findByText('No fine records')).toBeInTheDocument();
});
it('shows absent related records and paginates each related section independently',async()=>{
  const {fetcher}=setup(`/fines/${fineId}`,url=>url.pathname.endsWith(fineId)?json(fine):json(page([],Number(url.searchParams.get('page')),21)));await login();
  await screen.findByText('No linked investigations');await screen.findByText('No related disputes');
  const casesSection=screen.getByRole('heading',{name:'Related investigations'}).closest('section');
  await userEvent.click(within(casesSection).getByRole('button',{name:'Next'}));
  await waitFor(()=>expect(requestParams(fetcher).at(-1).get('page')).toBe('2'));
  const disputesSection=screen.getByRole('heading',{name:'Related disputes'}).closest('section');
  expect(within(disputesSection).getByText('21 total · Page 1 of 2')).toBeInTheDocument();
});
it('handles fine not-found and invalid-ID deep links',async()=>{
  const {router,fetcher}=setup(`/fines/${fineId}`,()=>json({error:{message:'Fine Record not found'}},404));await login();expect(await screen.findByRole('alert')).toHaveTextContent('could not be found');
  const count=fetcher.mock.calls.length;await act(async()=>router.navigate('/fines/not-a-uuid'));expect(screen.getByRole('alert')).toHaveTextContent('Expected a UUID');expect(fetcher).toHaveBeenCalledTimes(count);
});
it('keeps detail records from a previous fine from replacing a newer fine',async()=>{
  let finish;const {router}=setup(`/fines/${fineId}`,url=>{
    if(url.pathname===`${finesPath}/${fineId}`)return new Promise(resolve=>{finish=resolve;});
    if(url.pathname===`${finesPath}/${otherId}`)return json({...fine,id:otherId,external_fine_id:'NEW-FINE'});
    return json(page());
  });await login();await act(async()=>router.navigate(`/fines/${otherId}`));await screen.findByRole('heading',{level:1,name:'NEW-FINE'});
  await act(async()=>finish(json(fine)));expect(screen.queryByRole('heading',{level:1,name:'TEST-FINE-101'})).not.toBeInTheDocument();expect(screen.getByRole('heading',{level:1,name:'NEW-FINE'})).toBeInTheDocument();
});
