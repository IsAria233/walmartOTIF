import {useState} from 'react';
import {pretty} from '../components/Records';
import {RecordDetails, sourceIndex} from './Evidence';

// Tool names as a person would say them: get_gate_log -> "Gate log".
export const toolLabel = name => pretty(String(name).replace(/^get_/, ''));

const VERDICTS = {supported: 'Supported', ruled_out: 'Ruled out', not_determined: 'Not determined'};

/** What the Agent reported for one run, in the shape the Agent returns it. */
export function AgentAssessment({findings, onInspect, shownAbove}) {
  const facts = findings.verified_facts || [];
  const causes = findings.causes_checked || [];
  const injected = findings.injected_instructions || [];
  return <>
    {findings.summary && <p className="record-text">{findings.summary}</p>}
    <p>Cause: <strong>{findings.cause === 'HANDOFF' ? 'None — handed to a person' : findings.cause || 'Not supplied'}</strong> · Confidence: {findings.confidence || 'Not supplied'}</p>
    {findings.handoff_note && findings.handoff_note !== shownAbove && <p className="record-text">{findings.handoff_note}</p>}
    {!!injected.length && <div className="note"><strong>Instructions found in supplier text (ignored and reported)</strong><ul>{injected.map((text, index) => <li key={index}>{text}</li>)}</ul></div>}
    <h3>Causes checked</h3>
    {causes.length ? <ul>{causes.map((item, index) => <li key={index}><strong>{item.cause}</strong> · {VERDICTS[item.verdict] || pretty(item.verdict)}: {item.reason}</li>)}</ul> : <p>No causes were checked.</p>}
    <h3>Verified facts</h3>
    {facts.length ? facts.map((item, index) => <div className="fact" key={index}>
      <p className="record-text">{item.fact}</p>
      <div className="action-row">{(item.source_records || []).map(ref => onInspect
        ? <button className="btn small" key={`${ref.record_type}:${ref.record_id}`} onClick={() => onInspect(ref)}>Inspect {pretty(ref.record_type)} · {ref.record_id}</button>
        : <span className="badge gray" key={`${ref.record_type}:${ref.record_id}`}>{pretty(ref.record_type)}</span>)}
        {!item.source_records?.length && <span className="annotation">No record cited.</span>}
      </div>
    </div>) : <p>No facts were verified.</p>}
  </>;
}

/** The tools a run called, in order, with any rejected submission explained. */
export function ToolActivity({log}) {
  return <ol>{log.map((entry, index) => <li key={index}>
    {entry.tool === 'submit_findings' ? `Submitted findings — ${entry.accepted ? 'accepted' : 'rejected'}` : `Read ${toolLabel(entry.tool)}`}
    {entry.error && ` — failed: ${entry.error}`}
    {!!entry.problems?.length && <ul>{entry.problems.map((problem, at) => <li key={at}>{problem}</li>)}</ul>}
  </li>)}</ol>;
}

/**
 * A handed-off case has no stored Finding: the Agent's work is kept on the handoff
 * record. This shows it where the reviewer looks for the Agent's conclusion.
 */
export default function HandoffAssessment({handoff, context, evidence}) {
  const [source, setSource] = useState(null);
  const details = handoff.handoff_details || {};
  const findings = details.findings;
  const tools = details.tools_called || [];
  const records = sourceIndex(context);
  const inspect = ref => setSource({type: ref.record_type, id: ref.record_id, record: records.get(`${ref.record_type}:${ref.record_id}`)});
  return <>
    <p className="badge gray">Agent assessment at handoff — not a stored Finding, not sent to the rules engine</p>
    {findings
      ? <AgentAssessment findings={findings} onInspect={evidence ? inspect : null} shownAbove={handoff.reason}/>
      : <p>{tools.length ? 'The Agent read records but did not reach findings it could submit.' : 'The case was handed off before the Agent examined any records.'}</p>}
    {!evidence && <><h3>Records the Agent read</h3>{tools.length ? <ul>{tools.map((name, index) => <li key={index}>{toolLabel(name)}</li>)}</ul> : <p>None.</p>}</>}
    {evidence && !findings?.verified_facts?.length && <p>No cited evidence is available for this handoff.</p>}
    {source && <><button className="btn small" onClick={() => setSource(null)}>Close evidence</button><RecordDetails source={source}/></>}
  </>;
}
