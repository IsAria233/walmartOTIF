import {useState} from 'react';
import {Link, useParams, useSearchParams} from 'react-router-dom';
import {domainPath, isUUID, positiveInt} from '../api/domain';
import useRead from '../hooks/useRead';
import {CaseTable, Money, PageHead, Pagination, ReadState, Status, Timestamp, pretty} from '../components/Records';
import {ErrorState} from '../components/States';

export function FineList() {
  const [params,setParams] = useSearchParams();
  const page = positiveInt(params.get('page'),1);
  const page_size = Math.min(100,positiveInt(params.get('page_size'),20));
  const resource = useRead(domainPath('fine-records',{page,page_size}));
  return <><PageHead title="Fine Records" subtitle="Browse recorded OTIF fines and their related investigations." refresh={resource.refresh}/><section className="card"><div className="cardhead"><h2>Recorded fines</h2>{resource.data && <span className="badge gray">{resource.data.total} fines</span>}</div><ReadState resource={resource} empty="No fine records">{resource.data && <>
    {!!resource.data.items.length && <div className="tablewrap"><table><caption className="sr-only">Fine records</caption><thead><tr><th>Fine record</th><th>PO Line ID</th><th>Metric</th><th>Original amount</th><th>Status</th><th>Created</th></tr></thead><tbody>{resource.data.items.map(fine => <tr key={fine.id}><td><Link className="link" to={`/fines/${encodeURIComponent(fine.id)}`}>{fine.external_fine_id || fine.id}</Link>{fine.external_fine_id && <span className="subid record-id">{fine.id}</span>}</td><td className="record-id">{fine.po_line_id}</td><td>{pretty(fine.metric)}</td><td><Money value={fine.original_amount}/></td><td><Status value={fine.status}/></td><td><Timestamp value={fine.created_at}/></td></tr>)}</tbody></table></div>}
    <Pagination data={resource.data} onPage={page => setParams({page,page_size})} onSize={page_size => setParams({page:1,page_size})}/></>}</ReadState></section></>;
}
function RelatedCases({fineId}) {
  const [page,setPage] = useState(1);
  const resource = useRead(domainPath('investigation-cases',{fine_record_id:fineId,page,page_size:20,sort_by:'created_at',sort_order:'desc'}));
  return <section className="card related"><div className="cardhead"><h2>Related investigations</h2><button className="btn small" onClick={resource.refresh}>Refresh investigations</button></div><ReadState resource={resource} empty="No linked investigations">{resource.data && <>{!!resource.data.items.length && <CaseTable items={resource.data.items}/>}<Pagination data={resource.data} onPage={setPage}/></>}</ReadState></section>;
}
function RelatedDisputes({fineId}) {
  const [page,setPage] = useState(1);
  const resource = useRead(domainPath(`fine-records/${encodeURIComponent(fineId)}/disputes`,{page,page_size:20}));
  return <section className="card related"><div className="cardhead"><h2>Related disputes</h2><button className="btn small" onClick={resource.refresh}>Refresh disputes</button></div><ReadState resource={resource} empty="No related disputes">{resource.data && <>{!!resource.data.items.length && <div className="tablewrap"><table><caption className="sr-only">Related disputes</caption><thead><tr><th>Dispute / supplier ID</th><th>Submitted</th><th>Reason</th><th>Dispute amount</th><th>Status</th></tr></thead><tbody>{resource.data.items.map(dispute => <tr key={dispute.id}><td><strong>{dispute.external_dispute_id || dispute.id}</strong><span className="subid record-id">{dispute.id}</span><span className="subid record-id">Supplier: {dispute.supplier_id}</span></td><td><Timestamp value={dispute.submitted_at}/></td><td className="record-text">{pretty(dispute.reason_category)}{dispute.reason_text && <p>{dispute.reason_text}</p>}</td><td><Money value={dispute.amount_disputed}/><span className="subid">Entire dispute</span></td><td><Status value={dispute.status}/></td></tr>)}</tbody></table></div>}<Pagination data={resource.data} onPage={setPage}/></>}</ReadState></section>;
}
export function FineDetail() {
  const {fineId} = useParams();
  const resource = useRead(isUUID(fineId) ? domainPath(`fine-records/${encodeURIComponent(fineId)}`) : null, false);
  if (!isUUID(fineId)) return <ErrorState message="Invalid Fine Record ID. Expected a UUID."/>;
  const fine = resource.data;
  return <><Link className="crumb-back" to="/fines">← Back to Fine Records</Link><PageHead title={fine?.external_fine_id || 'Fine Record'} subtitle={fineId} refresh={resource.refresh}/><ReadState resource={resource}>{fine && <>
    <section className="card"><div className="cardhead"><h2>Fine details</h2><Status value={fine.status}/></div><dl className="fine-fields">{[
      ['Fine Record ID',fine.id],['External Fine ID',fine.external_fine_id],['PO Line ID',fine.po_line_id],['PO Line Version ID',fine.po_line_version_id],['PO version used',fine.po_version_used],['Metric',pretty(fine.metric)],['Ordered cases',fine.ordered_cases],['Received cases',fine.received_cases],['Non-compliant cases',fine.non_compliant_cases],['System accountability',pretty(fine.system_accountability)],['Original amount',<Money key="original" value={fine.original_amount}/>],['Case cost snapshot',<Money key="cost" value={fine.case_cost_snapshot}/>],['Fine rate (fraction)',fine.fine_rate],['Recorded arrival',<Timestamp key="arrival" value={fine.recorded_arrival_ts}/>],['Created',<Timestamp key="created" value={fine.created_at}/>],
    ].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value ?? 'Not recorded'}</dd></div>)}</dl></section>
    <RelatedCases key={`cases-${fineId}`} fineId={fineId}/><RelatedDisputes key={`disputes-${fineId}`} fineId={fineId}/>
  </>}</ReadState></>;
}
