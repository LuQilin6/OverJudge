import { ArrowDownToLine, Gavel, Play } from 'lucide-react';
import type { EvidenceRef, ReviewReport } from '../../shared/reviews';
import type { Perspective } from '../review-session';
import { formatTime } from '../video';
export function Verdict({ report, clips, onSeek, onExport }: { report: ReviewReport; clips: Perspective[]; onSeek: (ref: EvidenceRef) => void; onExport: () => void }) {
  const name = (id: string) => clips.find(c => c.id === id)?.label ?? id;
  const stamps = (refs: EvidenceRef[]) => <div className="timestamp-row">{refs.map((ref, i) => <button key={i} className="stamp" onClick={() => onSeek(ref)} aria-label={`View ${name(ref.povId)} at ${formatTime(ref.start)}`}><Play size={10} />{name(ref.povId)} · {formatTime(ref.start)}–{formatTime(ref.end)}</button>)}</div>;
  return <div className="report-content">
    <div className="verdict-card"><div className="eyebrow"><Gavel size={14} />THE VERDICT</div><h2>{{ inconclusive: 'Not enough evidence for blame.', shared: 'More than one decision mattered.', supported: 'A decision made a difference.' }[report.verdict]}</h2><p>{report.summary}</p><div className="confidence">{report.confidence.label} confidence</div><p className="confidence-reason">{report.confidence.rationale}</p></div>
    <p>{report.fightSummary}</p>
    {report.evidence.length > 0 && <div className="section-label">WHAT WE CAN SEE</div>}
    {report.evidence.map((e, i) => <article className="evidence" key={i}>{stamps(e.refs)}<h3>{e.observation}</h3></article>)}
    {report.decisions.length > 0 && <div className="section-label">INTERPRETATIONS & CONTRIBUTING DECISIONS</div>}
    {report.decisions.map((d, i) => <article className="decision" key={i}><span className="mini-label">{name(d.pov_id)} · {d.level === 'not_established' ? 'UNESTABLISHED — NOT AN ADVERSE FINDING' : d.level}</span><h3>{d.claim}</h3>{stamps(d.refs)}<p>{d.causal_reasoning}</p><p><strong>What the player knew:</strong> {d.player_information}</p><p><strong>Another explanation:</strong> {d.alternative_explanation}</p><p><strong>Try instead:</strong> {d.alternative_action}</p></article>)}
    <div className="section-label">EACH PERSPECTIVE</div>{report.players.map(p => <article className="decision" key={p.povId}><h3>{name(p.povId)}</h3><p>{p.summary}</p></article>)}
    {report.coaching.map((c, i) => <article className="coaching" key={i}><div><div className="eyebrow">NEXT MATCH · {c.povIds.map(name).join(', ')}</div><p>{c.lesson}</p>{stamps(c.refs)}</div></article>)}
    <details className="limits" open><summary>What the footage can’t tell us</summary><ul>{report.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></details>
    <button className="export-button" onClick={onExport}><ArrowDownToLine size={15} />Download report <span>JSON</span></button>
  </div>;
}
