import {Link} from 'react-router-dom';
import {EmptyState, ErrorState, Loading} from './States';
// Field and type names as labels: po_line -> "PO line", asn -> "ASN".
export const pretty = value => value ? String(value).replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()).replace(/\b(po|asn|dc|id|mabd|bol|pod)\b/gi, word => word.toUpperCase()) : 'Not recorded';
/** One record as a labelled list. Nested records are listed inside their field; lists stay as compact JSON. */
export function Fields({record}) {
  const entries = Object.entries(record || {}).filter(([, value]) => value !== null && value !== '');
  if (!entries.length) return <p>No fields recorded.</p>;
  return <dl className="fine-fields">{entries.map(([key, value]) => (
    <div key={key}>
      <dt>{pretty(key)}</dt>
      <dd className="record-text">{Array.isArray(value) ? JSON.stringify(value) : typeof value === 'object' ? <Fields record={value}/> : String(value)}</dd>
    </div>
  ))}</dl>;
}

export function Timestamp({value}) {
  return value ? <time dateTime={value} title={value}>{new Date(value).toLocaleString(undefined, {timeZoneName: 'short'})}</time> : 'Not recorded';
}
export function Money({value}) {
  // Stored decimal strings are shown without financial recomputation.
  return value == null ? 'Not recorded' : `$${value}`;
}
export function Status({value}) {
  const color = ({closed:'green', investigating:'blue', awaiting_approval:'amber', handed_off:'amber', revision_required:'red'})[value] || 'gray';
  return <span className={`badge ${color}`}>{pretty(value)}</span>;
}
export function PageHead({title, subtitle, refresh}) {
  return <div className="records-head"><div><div className="eyebrow">Operations / Workspace</div><h1>{title}</h1><p className="subtitle">{subtitle}</p></div><button className="btn" onClick={refresh}>↻ Refresh</button></div>;
}
export function Pagination({data, onPage, onSize}) {
  return <div className="tablefoot"><span>{data.total} total · Page {data.page} of {Math.max(data.total_pages, 1)}</span><div className="paging-controls">
    {onSize && <label>Rows per page <select aria-label="Rows per page" value={data.page_size} onChange={e => onSize(Number(e.target.value))}>{[...new Set([20, 50, 100, data.page_size])].sort((a,b)=>a-b).map(size => <option key={size}>{size}</option>)}</select></label>}
    <button className="btn small" onClick={() => onPage(1)} disabled={data.page <= 1}>First</button><button className="btn small" onClick={() => onPage(data.page - 1)} disabled={data.page <= 1}>Previous</button><button className="btn small" onClick={() => onPage(data.page + 1)} disabled={data.page >= data.total_pages}>Next</button>
  </div></div>;
}
export function ReadState({resource, empty, children}) {
  if (resource.loading) return <Loading message="Loading records…"/>;
  if (resource.error) return <ErrorState message={resource.error.status === 404 ? 'This record could not be found.' : resource.error.message} onRetry={resource.refresh}/>;
  if (!resource.data) return null;
  if (Array.isArray(resource.data.items) && !resource.data.items.length) return <><EmptyState title={empty || 'No records found'}>No records match this view.</EmptyState>{children}</>;
  return children;
}
export function CaseTable({items}) {
  return <div className="tablewrap"><table><caption className="sr-only">Investigation cases</caption><thead><tr><th scope="col">Case</th><th scope="col">Status</th><th scope="col">PO line</th><th scope="col">Supplier</th><th scope="col">Fine type</th><th scope="col">Fine amount</th><th scope="col">Origin</th><th scope="col">Created</th></tr></thead><tbody>{items.map(item => <tr key={item.id}>
    <td><Link className="link" to={`/cases/${encodeURIComponent(item.id)}`}>{item.summary?.external_fine_id || item.id}</Link>{item.summary?.external_fine_id && <span className="subid record-id">{item.id}</span>}<Link className="subid link" to={`/fines/${encodeURIComponent(item.fine_record_id)}`}>Fine record</Link></td><td><Status value={item.status}/></td>
    <td>{item.summary ? `${item.summary.po_number} · line ${item.summary.line_number}` : 'Not recorded'}</td><td>{item.summary?.supplier_name || 'Not recorded'}</td><td>{pretty(item.summary?.metric)}</td><td><Money value={item.summary?.original_amount}/></td>
    <td>{pretty(item.origin)}</td><td><Timestamp value={item.created_at}/></td></tr>)}</tbody></table></div>;
}
