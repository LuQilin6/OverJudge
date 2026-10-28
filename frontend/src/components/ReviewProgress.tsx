import { useEffect, useRef, useState } from 'react';
import { Check, Clock3, FileCheck2, LoaderCircle, X } from 'lucide-react';
import type { ReviewJob } from '../api/contracts';
import { formatTime } from '../video';
import { Mascot } from './Mascot';
import './review-progress.css';

type Stage = { id: ReviewJob['state']; title: string; description: string };
const preparation: Stage[] = [
  { id: 'uploading', title: 'Receive the evidence', description: 'Sending your recordings to the local review server.' },
  { id: 'preparing', title: 'Prepare the footage', description: 'Aligning the recordings and selecting frames to inspect.' },
];
const automatic: Stage[] = [
  ...preparation,
  { id: 'observing', title: 'Examine each perspective', description: 'Inspecting the sampled frames from each player’s view.' },
  { id: 'comparing', title: 'Reconstruct the fight', description: 'Putting the visible events in order and comparing the available views.' },
  { id: 'judging', title: 'Weigh the evidence', description: 'Considering the decisions, missing context, and possible explanations.' },
  { id: 'auditing', title: 'Check the verdict', description: 'A separate AI review checks the claims against the cited footage.' },
  { id: 'awaiting_review', title: 'Validate the case file', description: 'Checking the final report before it can be shown to you.' },
];
const manual: Stage[] = [
  ...preparation,
  { id: 'awaiting_review', title: 'Hand over to the reviewer', description: 'The evidence is ready for manual inspection. No AI model is running automatically.' },
];

export function getReviewProgress(state: ReviewJob['state'] | undefined, isManual: boolean) {
  const stages = isManual ? manual : automatic;
  const current = state === 'complete' ? stages.length : stages.findIndex(stage => stage.id === (state === 'queued' ? 'observing' : state ?? 'uploading'));
  const waiting = state === 'queued' || (isManual && state === 'awaiting_review');
  return { stages, current, waiting };
}

export function ReviewProgress({ job, execution, onCancel }: {
  job: ReviewJob | null; execution: string; onCancel: () => void;
}) {
  const isManual = execution === 'manual';
  const { stages, current, waiting } = getReviewProgress(job?.state, isManual);
  const started = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  const stopped = job?.state === 'failed' || job?.state === 'cancelled';
  const finished = job?.state === 'complete';
  useEffect(() => {
    if (stopped || finished) return;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started.current) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [stopped, finished]);
  const currentStage = stages[current];
  const completed = Math.max(0, Math.min(current, stages.length));
  const title = stopped ? 'The review has stopped.' : finished ? 'Your case file is ready.' : waiting ? (isManual ? 'Ready for the reviewer.' : 'Waiting for the judge.') : currentStage?.title ?? 'Checking the review status.';
  const message = job?.message || 'Opening your case and receiving the recordings.';
  const prepared = Math.min(job?.total ?? 0, new Set(job?.prepared).size);

  return <section className="review-progress" aria-label="Live review progress">
    <aside className={`review-live-card ${waiting ? 'is-waiting' : ''}`}>
      <div className="review-live-top"><span className="mini-label">{waiting ? 'CASE ON STANDBY' : stopped ? 'REVIEW STOPPED' : finished ? 'CASE REVIEWED' : 'THE JUDGE IS ON THE CASE'}</span><span className="review-elapsed" aria-label={`Elapsed time ${formatTime(elapsed)}`}><Clock3 size={13} aria-hidden="true" />{formatTime(elapsed)}</span></div>
      <div className="review-progress-mascot"><Mascot pose={finished ? 'presenting' : 'examining'} bob={!waiting && !stopped && !finished} /></div>
      <div className="review-current-copy" role="status" aria-live="polite" aria-atomic="true">
        <p className="review-stage-position">{stopped ? 'REVIEW ENDED' : finished ? 'ALL STEPS COMPLETE' : current < 0 ? 'CHECKING STATUS' : `STEP ${current + 1} OF ${stages.length}`}</p>
        <h3>{title}</h3><p>{message}</p>
      </div>
      {!waiting && !stopped && !finished && <div className="review-activity" aria-hidden="true"><span /><span /><span /></div>}
      <p className="review-time-note">{waiting ? (isManual ? 'This window will check for the submitted result.' : 'Your place is reserved. The review will start when the local reviewer is available.') : 'Some steps take longer than others. This checklist shows actual stages, not a time estimate.'}</p>
    </aside>
    <div className="review-checklist">
      <div className="review-checklist-heading"><div><p className="mini-label">FROM EVIDENCE TO VERDICT</p><h3>The court’s checklist</h3></div><span>{completed}/{stages.length} done</span></div>
      <ol className="review-stage-list" aria-label="Review stages">
        {stages.map((stage, index) => {
          const active = index === current;
          const done = index < current;
          const status = done ? 'Complete' : active ? (waiting ? 'Waiting' : 'In progress') : 'Not started';
          return <li key={stage.id} className={`review-stage ${done ? 'is-complete' : active ? (waiting ? 'is-waiting' : 'is-active') : 'is-pending'}`} aria-current={active ? 'step' : undefined}>
            <span className="review-stage-marker" aria-hidden="true">{done ? <Check size={18} /> : active ? (waiting ? <Clock3 size={18} /> : <LoaderCircle className="review-stage-spinner" size={19} />) : String(index + 1).padStart(2, '0')}</span>
            <div className="review-stage-content"><div className="review-stage-heading"><h4><span>{String(index + 1).padStart(2, '0')}.</span> {stage.title}</h4><span className="review-stage-status">{status}</span></div>
              {active && <div className="review-stage-detail"><p>{waiting && !isManual ? 'Queued for the local reviewer; inspection has not started yet.' : stage.description}</p>
                {stage.id === 'preparing' && Boolean(job?.total) && <div className="review-preparation"><span>{prepared} of {job!.total} recordings prepared</span><progress aria-label="Recordings prepared" max={job!.total} value={prepared} /></div>}
              </div>}
            </div>
          </li>;
        })}
      </ol>
      {isManual && job?.state === 'awaiting_review' && <details className="operator-details"><summary>Reviewer handoff</summary><p>Review ID: <code>{job.id}</code></p><p>Open <code>.local/reviews/{job.id}/REVIEW.md</code> in the integrated project. This window checks for the published result automatically.</p></details>}
      <div className="review-progress-actions"><p><FileCheck2 size={16} aria-hidden="true" />Closing this window cancels the review. Your clips and answers stay available for a retry.</p><button className="text-button" onClick={onCancel}><X size={15} />Cancel review</button></div>
    </div>
  </section>;
}
