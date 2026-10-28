import { ArrowDownToLine, Eye, Gavel, Play, Sparkles, Users } from 'lucide-react';
import type { EvidenceRef, ReviewReport } from '../api/contracts';
import type { Perspective } from '../review-session';
import { formatTime } from '../video';
import './verdict.css';

type ReportPlayer = Pick<Perspective, 'id' | 'label' | 'hero' | 'role'>;
export function Verdict({ report, clips, onSeek, onExport, preview = false }: {
  report: ReviewReport; clips: ReportPlayer[]; onSeek: (ref: EvidenceRef) => void; onExport: () => void; preview?: boolean;
}) {
  const name = (id: string) => clips.find(c => c.id === id)?.label || id;
  const stamps = (refs: EvidenceRef[]) => <div className="timestamp-row">{refs.map((ref, i) => preview
    ? <span key={i} className="stamp sample-stamp">{name(ref.povId)} · {formatTime(ref.start)}–{formatTime(ref.end)}</span>
    : <button key={i} className="stamp" onClick={() => onSeek(ref)} aria-label={`View ${name(ref.povId)} at ${formatTime(ref.start)}`}><Play size={12} />{name(ref.povId)} · {formatTime(ref.start)}–{formatTime(ref.end)}</button>)}</div>;
  const estimates = report.players.filter(p => typeof p.responsibilityPercent === 'number' && Number.isFinite(p.responsibilityPercent)).sort((a, b) => b.responsibilityPercent! - a.responsibilityPercent!);
  const supported = report.decisions.filter(d => d.level !== 'not_established');
  return <div className="report-content">
    <section className={`verdict-card result-${report.verdict}`} aria-labelledby="verdict-heading">
      <div className="verdict-topline"><span className="eyebrow"><Gavel size={16} />THE VERDICT</span><span className="result-confidence">{preview ? 'Reconstruction only' : `${report.confidence.label} confidence`}</span></div>
      <h2 id="verdict-heading">{preview ? 'The fight reconstructed. Judgment pending.' : { inconclusive: estimates.length ? 'The judge’s best guess.' : 'Not enough evidence for blame.', shared: 'More than one decision mattered.', supported: 'A decision made a difference.' }[report.verdict]}</h2>
      <p>{report.summary}</p>
      <details className="confidence-detail"><summary>Why this confidence level?</summary><p>{report.confidence.rationale}</p></details>
    </section>
    {!preview && estimates.length > 0 && <section className="responsibility-card" aria-labelledby="responsibility-heading">
      <span className="eyebrow">THE JUDGE’S CALL</span>
      <h3 id="responsibility-heading">{report.players.length === 1 ? 'How much blame is on you?' : 'Who takes the blame?'}</h3>
      <p className="responsibility-caption">{report.players.length === 1 ? 'Higher % means more blame for what went wrong. The rest is unallocated context.' : 'Higher % means more blame for what went wrong — not more credit for a good play.'}</p>
      <ol className="responsibility-list">{estimates.map(p => <li key={p.povId}>
        <div className="responsibility-label"><strong>{name(p.povId)}</strong><span>{p.responsibilityPercent}%</span></div>
        <div className="responsibility-track" aria-hidden="true"><div style={{ width: `${Math.max(0, Math.min(100, p.responsibilityPercent!))}%` }} /></div>
        <p><strong>{p.status === 'findings' ? 'Why the judge assigns blame: ' : 'Suspected fault (speculative): '}</strong>{p.summary}</p>
      </li>)}</ol>
      <p className="responsibility-note">A subjective judge’s estimate — not a measured fact or a verdict on the whole match.{report.verdict === 'inconclusive' ? ' This split is speculative; the footage does not establish fault.' : ''}</p>
    </section>}
    <div className="result-stats" aria-label="Report overview"><span><Eye size={16} /><strong>{report.evidence.length}</strong> observations</span><span><Users size={16} /><strong>{report.players.length}</strong> perspectives</span><span><Gavel size={16} /><strong>{supported.length}</strong> supported findings</span></div>
    <section className="result-section"><h3>This moment, in context</h3><p>{report.fightSummary}</p></section>
    <section className="result-section" aria-labelledby="evidence-heading"><div className="result-section-heading"><h3 id="evidence-heading">What the footage shows</h3><span>OBSERVED</span></div>
      <p className="result-help">{preview ? 'Timestamps reference the example recordings. Playback is available with your own reviewed clips.' : 'Select a timestamp to jump to that player’s recording.'}</p>
      {report.evidence.length ? <ol className="result-timeline">{report.evidence.map((e, i) => <li key={i}><span className="evidence-number">{String(i + 1).padStart(2, '0')}</span><div><p>{e.observation}</p>{stamps(e.refs)}</div></li>)}</ol> : <p className="result-empty">No gameplay observations were established from this footage.</p>}
    </section>
    <section className="result-section"><h3>Decisions that mattered</h3>
      {!report.decisions.length && <p className="result-empty">{preview ? 'This example stops at reconstruction. Contributing decisions and coaching require a final judgment.' : 'No individual mistake was established. An incomplete view is not proof of fault.'}</p>}
      {report.decisions.map((d, i) => <article className={`result-decision ${d.level === 'not_established' ? 'unestablished' : ''}`} key={i}><span className="mini-label">{name(d.pov_id)} · {d.level === 'not_established' ? 'UNESTABLISHED HYPOTHESIS' : `${d.level.toUpperCase()} CONTRIBUTION`}</span><h4>{d.claim}</h4>{d.level === 'not_established' && <p className="hypothesis-note">This is not a supported finding against the player.</p>}<p>{d.causal_reasoning}</p>{stamps(d.refs)}<details><summary>See the reasoning & alternatives</summary><dl><dt>What the player knew</dt><dd>{d.player_information}</dd><dt>Another explanation</dt><dd>{d.alternative_explanation}</dd><dt>An alternative action</dt><dd>{d.alternative_action}</dd></dl></details></article>)}
    </section>
    <section className="result-section"><h3>Each player’s perspective</h3><div className="result-players">{report.players.map(p => { const player = clips.find(c => c.id === p.povId); return <article key={p.povId}><div className="result-player-heading"><span className="player-initial" aria-hidden="true">{name(p.povId).slice(0, 1).toUpperCase()}</span><div><h4>{name(p.povId)}</h4>{(player?.hero || player?.role) && <span>{[player.hero, player.role].filter(Boolean).join(' · ')}</span>}</div></div><p>{p.summary}</p><span className="player-status">{preview ? 'Final judgment not supplied' : p.status === 'no_supported_mistake' ? 'No supported mistake' : 'See contributing decisions'}</span></article>; })}</div></section>
    {report.coaching.length > 0 && <section className="result-section result-coaching"><h3><Sparkles size={18} /> Take into your next match</h3>{report.coaching.map((c, i) => <article key={i}><span className="mini-label">{c.povIds.map(name).join(', ')}</span><p>{c.lesson}</p>{stamps(c.refs)}</article>)}</section>}
    <details className="limits result-limits" open><summary>What the footage can’t tell us</summary><ul>{report.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></details>
    <button className="export-button" onClick={onExport}><ArrowDownToLine size={16} />{preview ? 'Download example report' : 'Download report'}<span>JSON</span></button>
  </div>;
}
