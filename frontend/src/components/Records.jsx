import {Link} from 'react-router-dom';
import {EmptyState, ErrorState, Loading} from './States';
export const pretty = value => value ? String(value).replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()) : 'Not recorded';
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
  return <div className="tablewrap"><table><caption className="sr-only">Investigation cases</caption><thead><tr><th scope="col">Case ID</th><th scope="col">Fine Record ID</th><th scope="col">Origin</th><th scope="col">Created</th><th scope="col">Status</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><Link className="link record-id" to={`/cases/${encodeURIComponent(item.id)}`}>{item.id}</Link></td><td><Link className="link record-id" to={`/fines/${encodeURIComponent(item.fine_record_id)}`}>{item.fine_record_id}</Link></td><td>{pretty(item.origin)}</td><td><Timestamp value={item.created_at}/></td><td><Status value={item.status}/></td></tr>)}</tbody></table></div>;
}
