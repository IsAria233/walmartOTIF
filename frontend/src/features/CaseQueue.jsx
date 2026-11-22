import {useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {CASE_STATUSES, ORIGINS, UUID_PATTERN, domainPath, positiveInt} from '../api/domain';
import useRead from '../hooks/useRead';
import {CaseTable, PageHead, Pagination, ReadState, pretty} from '../components/Records';
import {ErrorState} from '../components/States';

function Filters({params, onApply}) {
  const [error, setError] = useState('');
  function apply(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (values.created_from && values.created_to && values.created_from > values.created_to) { setError('Created from must be before or equal to Created to.'); return; }
    for (const field of ['created_from', 'created_to']) if (values[field]) values[field] = new Date(values[field]).toISOString();
    onApply(values);
  }
  function localDate(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return '';
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,16);
  }
  return <form className="queue-filters" onSubmit={apply} aria-label="Case filters">
    <label>Status<select name="status" defaultValue={params.get('status') || ''}><option value="">All statuses</option>{CASE_STATUSES.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
    <label>Origin / source<select name="origin" defaultValue={params.get('origin') || params.get('source') || ''}><option value="">All origins</option>{ORIGINS.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
    <label>Fine Record ID<input name="fine_record_id" defaultValue={params.get('fine_record_id') || ''} pattern={UUID_PATTERN} title="Enter a UUID" placeholder="UUID"/></label>
    <label>Supplier ID<input name="supplier_id" defaultValue={params.get('supplier_id') || ''} pattern={UUID_PATTERN} title="Enter a UUID" placeholder="UUID"/></label>
    <label>Created from (local time)<input type="datetime-local" name="created_from" defaultValue={localDate(params.get('created_from'))}/></label>
    <label>Created to (local time)<input type="datetime-local" name="created_to" defaultValue={localDate(params.get('created_to'))}/></label>
    <div className="action-row"><button className="btn primary" type="submit">Apply filters</button><button className="btn" type="button" onClick={() => onApply({status:'', origin:'', fine_record_id:'', supplier_id:'', created_from:'', created_to:''})}>Clear filters</button></div>
    {error && <ErrorState message={error}/>}
  </form>;
}
export default function CaseQueue() {
  const [params, setParams] = useSearchParams();
  const options = {page: positiveInt(params.get('page'), 1), page_size: Math.min(100, positiveInt(params.get('page_size'),20)), sort_by: ['created_at','status','origin'].includes(params.get('sort_by')) ? params.get('sort_by') : 'created_at', sort_order: params.get('sort_order') === 'asc' ? 'asc' : 'desc'};
  for (const key of ['status','origin','fine_record_id','supplier_id','created_from','created_to']) if (params.get(key)) options[key] = params.get(key);
  if (!options.origin && params.get('source')) options.origin = params.get('source');
  const resource = useRead(domainPath('investigation-cases', options));
  function update(values) {
    const next = new URLSearchParams(params);
    if (!next.has('origin') && next.has('source')) next.set('origin', next.get('source'));
    next.delete('source');
    for (const [key,value] of Object.entries(values)) { if (value === '') next.delete(key); else next.set(key,value); }
    setParams(next);
  }
  return <><PageHead title="Investigation Queue" subtitle="Track exceptions and find investigations for review." refresh={resource.refresh}/><section className="card">
    <div className="cardhead"><h2>All investigations</h2>{resource.data && <span className="badge blue">{resource.data.total} results</span>}</div>
    <Filters key={params.toString()} params={params} onApply={values => update({...values,page:1})}/>
    <div className="toolbar"><label>Sort by <select aria-label="Sort by" value={options.sort_by} onChange={e => update({sort_by:e.target.value,page:1})}><option value="created_at">Created</option><option value="status">Status</option><option value="origin">Origin</option></select></label><label>Order <select aria-label="Sort order" value={options.sort_order} onChange={e => update({sort_order:e.target.value,page:1})}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label></div>
    <ReadState resource={resource} empty="No matching investigations">{resource.data && <>{!!resource.data.items.length && <CaseTable items={resource.data.items}/>}<Pagination data={resource.data} onPage={page => update({page})} onSize={page_size => update({page_size,page:1})}/></>}</ReadState>
  </section></>;
}
