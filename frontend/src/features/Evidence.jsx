import {useState} from 'react';
import {Fields, pretty} from '../components/Records';
export function sourceIndex(context) {
  const records = new Map();
  function add(type, record) { if (record?.id) records.set(`${type}:${record.id}`,record); }
  add('fine_record',context?.fine_record); add('po_line',context?.po_line);
  for (const record of context?.po_line_versions || []) add('po_line_version',record);
  for (const item of context?.asns || []) { add('asn',item.asn); for(const line of item.lines || []) add('asn_line',line); }
  for (const record of context?.appointments || []) add('appointment_event',record);
  for (const item of context?.deliveries || []) {
    add('delivery',item.delivery);add('asn_line',item.asn_line);
    for(const record of item.gate_logs || []) add('gate_log',record);
    for(const record of item.receiving_records || []) add('receiving_record',record);
  }
  for(const record of context?.weather_alerts || []) add('weather_alert',record);
  for(const item of context?.disputes || []) {add('dispute',item.dispute);for(const record of item.attachments || []) add('attachment',record);}
  for(const record of context?.attachments || []) add('attachment',record);
  return records;
}
export function RecordDetails({source}) {
  if(!source) return null;
  return <section className="evidence-detail" aria-label="Selected evidence"><h3>{pretty(source.type)} · {source.id}</h3><p className="badge gray">{['attachment','dispute'].includes(source.type) ? 'Supplier-provided claim' : 'Operational record / stored snapshot'}</p>
    {source.record ? <Fields record={source.record}/> : <p role="status">This reference is unavailable in the supplied context. No additional evidence-read API is provided.</p>}
  </section>;
}
export default function Evidence({finding, context, caseContext}) {
  const [source,setSource] = useState(null);
  const records=sourceIndex(context);
  const snapshots=new Map();
  // The context exposes snapshot links only for the latest Finding.
  if (finding?.id === caseContext?.latest_finding?.id) for(const item of caseContext.evidence_context || []) for(const entry of item.evidence_links || []) snapshots.set(entry.link.evidence_record_id, entry.evidence);
  return <><p className="annotation">Citations below are attached to facts by the backend. Source records are current context; evidence snapshots are shown only when supplied for this Finding.</p>
    {(finding?.facts || []).map(fact => <section className="fact" key={fact.id}><h3>{fact.fact_key}</h3><p className="record-text">{fact.fact_value || 'No fact value supplied'}</p>{fact.source_description && <p>{fact.source_description}</p>}<div className="action-row">
      {(fact.source_records || []).map(ref => <button className="btn small" key={`${ref.record_type}:${ref.record_id}`} onClick={() => setSource({type:ref.record_type,id:ref.record_id,record:records.get(`${ref.record_type}:${ref.record_id}`)})}>Inspect {pretty(ref.record_type)} · {ref.record_id}</button>)}
      {(fact.evidence_ids || []).map(id => <button className="btn small" key={id} onClick={() => setSource({type:'evidence_snapshot',id,record:snapshots.get(id)})}>Inspect snapshot · {id}</button>)}
      {!fact.source_records?.length && !fact.evidence_ids?.length && <span className="annotation">No citations supplied for this fact.</span>}
    </div></section>)}
    {!finding?.facts?.length && <p>No cited facts are available for this Finding.</p>}
    {source && <><button className="btn small" onClick={() => setSource(null)}>Close evidence</button><RecordDetails source={source}/></>}
  </>;
}
