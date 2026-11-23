import {useState} from 'react';
import useRead from '../hooks/useRead';
import {domainPath} from '../api/domain';
import {CaseTable, PageHead, Pagination, ReadState} from '../components/Records';

/** The manager's inbox: cases whose reversal is above the threshold and that the associate has approved. */
export default function ManagerReview() {
  const [page, setPage] = useState(1);
  const resource = useRead(domainPath('investigation-cases', {status: 'awaiting_approval', approval_stage: 'manager', page, page_size: 20, sort_by: 'created_at', sort_order: 'desc'}));
  return <><PageHead title="Manager Review" subtitle="Reversals above the threshold that an associate has approved and that wait for you." refresh={resource.refresh}/>
    <section className="card"><div className="cardhead"><h2>Waiting for manager approval</h2>{resource.data && <span className="badge gray">{resource.data.total} {resource.data.total === 1 ? "case" : "cases"}</span>}</div>
      <ReadState resource={resource} empty="Nothing is waiting for manager approval">{resource.data && <>{!!resource.data.items.length && <CaseTable items={resource.data.items}/>}<Pagination data={resource.data} onPage={setPage}/></>}</ReadState>
    </section></>;
}
