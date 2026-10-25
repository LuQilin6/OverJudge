import { useState } from 'react';
import { Agentation } from 'agentation';
import { motion, MotionConfig, useReducedMotion } from 'motion/react';
import { ArrowLeft, ArrowRight, Check, CircleHelp, Film, Plus, Upload, X } from 'lucide-react';
import { useReview } from './useReview';
import { formatTime } from './video';
import { ReplayScene } from './components/ReplayScene';
import { ReviewDialog } from './components/ReviewDialog';
import { Mascot } from './components/Mascot';
import { Verdict } from './components/Verdict';

export default function App() {
  const review = useReview();
  const [open, setOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const reduced = useReducedMotion();
  const view = review.busy ? 'review' : review.report ? 'verdict' : review.step;
  const heading = { upload: 'Let’s see the fight.', context: review.team ? 'Same fight. Different perspectives.' : 'What’s your side of the story?', review: review.job?.state === 'awaiting_review' ? 'Ready for a closer look.' : 'Setting up the evidence.', verdict: 'Here’s what the evidence says.' }[view];
  const subtitle = { upload: 'One recording or the whole squad. Add up to five perspectives of the same fight.', context: review.team ? 'Match a shared moment, then tell me what you want to understand.' : 'Your question helps. The footage still gets the final say.', review: 'This version prepares evidence for a manual reviewer; it does not run a model automatically.', verdict: 'A fair call, with the footage to back it up.' }[view];
  function drop(event: React.DragEvent) { event.preventDefault(); setDragging(false); review.addFiles(Array.from(event.dataTransfer.files)); }
  const choose = () => review.inputRef.current?.click();
  return <MotionConfig reducedMotion="user">
    <ReplayScene onOpen={() => setOpen(true)} hasClip={review.clips.length > 0} />
    <ReviewDialog open={open} onClose={() => { review.closeReview(); setOpen(false); }} title={heading} subtitle={subtitle} pose={view === 'review' ? 'examining' : view === 'verdict' ? 'presenting' : 'greeting'} step={view}>
      <div className="review-mode" role="status"><span className="mode-pill">{review.team ? 'Teamfight review' : 'Your play review'}</span><span>{review.clips.length}/5 perspectives</span></div>
      <ol className="flow-steps" aria-label="Review steps">{['The footage', 'Your question', 'The review'].map((label, i) => {
        const current = view === 'upload' ? 0 : view === 'context' ? 1 : 2;
        return <li key={label} className={i === current ? 'current' : i < current ? 'complete' : ''} aria-current={i === current ? 'step' : undefined}><span>{i < current ? <Check size={12} /> : `0${i + 1}`}</span>{label}</li>;
      })}</ol>
      {review.error && <div className="error-message" role="alert"><CircleHelp size={18} /><span>{review.error}</span><button className="icon-button" aria-label="Dismiss error" onClick={() => review.setError('')}><X size={16} /></button></div>}
      {review.notice && !review.busy && <p className="notice" role="status">{review.notice}</p>}
      <input ref={review.inputRef} tabIndex={-1} className="visually-hidden" aria-label="Choose gameplay clips" type="file" multiple accept="video/mp4,video/webm,.mp4,.webm" onChange={e => { review.addFiles(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
      <div className={`review-grid view-${view} ${review.clip ? 'with-clip' : ''}`}>
        <section className="clip-side" aria-label="Gameplay perspectives" hidden={!review.clip || view === 'review'}>
          {review.clip && <>
            <div className="perspective-tabs" role="group" aria-label="Choose video perspective">{review.clips.map(c => <button key={c.id} aria-pressed={review.clip?.id === c.id} onClick={() => review.setActiveId(c.id)}>{c.label || 'Unnamed player'}</button>)}</div>
            <div className="clip-preview"><video key={review.clip.url} ref={review.videoRef} src={review.clip.url} controls preload="metadata" playsInline onLoadedMetadata={review.applySeek} onError={() => review.setError('This recording cannot be played. Remove it and export an H.264 MP4 or WebM.')} /></div>
            <div className="clip-info"><span title={review.clip.file.name}><Film size={14} />{review.clip.file.name}</span><span>{review.clip.duration ? formatTime(review.clip.duration) : review.clip.error ? 'Invalid clip' : 'Loading…'}</span></div>
            {view === 'context' && review.team && <div className="alignment-panel"><strong>Mark the same visible event</strong><p>For example, the instant an ultimate starts. Find it in each video and set its marker.</p><label htmlFor="anchor">{review.clip.label}: event time in seconds</label><div className="marker-controls"><input id="anchor" type="number" min={0} max={review.clip.duration ?? 90} step="0.01" value={Number.isFinite(review.clip.anchor) ? review.clip.anchor : ''} onChange={e => review.updateClip(review.clip!.id, { anchor: e.target.valueAsNumber })} /><button type="button" className="text-button" onClick={() => review.updateClip(review.clip!.id, { anchor: Math.round((review.videoRef.current?.currentTime ?? 0) * 100) / 100 })}>Use current frame</button></div><ul className="marker-list">{review.clips.map(c => <li key={c.id}><button onClick={() => review.setActiveId(c.id)}>{c.label}</button><span>{Number.isFinite(c.anchor) ? `${c.anchor.toFixed(2)}s` : 'Set a marker'}</span></li>)}</ul><p className="field-hint">{review.interval ? `${review.interval.duration.toFixed(1)} seconds overlap. Only shared footage will be reviewed.` : 'Every marker must be inside its recording.'}</p></div>}
            <p className="privacy-note">Recordings are sent to this computer’s local pipeline when you submit. No automatic model call or audio analysis. Local review files expire after 24 hours when the server next cleans up.</p>
          </>}
        </section>
        <motion.section className="flow-content" key={view} initial={reduced ? false : { opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .22 }}>
          {view === 'upload' && <>
            {!review.clips.length ? <button className={`dropzone ${dragging ? 'dragging' : ''}`} onClick={choose} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}><span className="upload-illustration"><Film size={36} /><span><Upload size={18} /></span></span><strong>A fight has more than one side.</strong><span>Drop recordings here, or <b>browse files</b></span><small>1–5 clips · MP4 / WebM · Each 10–90s, up to 200 MB</small></button> : <>
              <div className="perspective-list">{review.clips.map((c, i) => <article className={`perspective-card ${c.error ? 'invalid' : ''}`} key={c.id}><div className="perspective-card-head"><span className="mini-label">PERSPECTIVE {i + 1}</span><button className="icon-button" aria-label={`Remove ${c.label}`} onClick={() => review.removeClip(c.id)}><X size={16} /></button></div><label htmlFor={`label-${c.id}`}>Player name</label><input id={`label-${c.id}`} maxLength={60} value={c.label} onChange={e => review.updateClip(c.id, { label: e.target.value })} /><div className="player-fields"><div><label htmlFor={`role-${c.id}`}>Role <span>optional</span></label><select id={`role-${c.id}`} value={c.role} onChange={e => review.updateClip(c.id, { role: e.target.value })}><option value="">Not specified</option>{['Tank', 'Damage', 'Support', 'Not sure'].map(r => <option key={r}>{r}</option>)}</select></div><div><label htmlFor={`hero-${c.id}`}>Hero <span>optional</span></label><input id={`hero-${c.id}`} maxLength={100} placeholder="e.g. Ana" value={c.hero} onChange={e => review.updateClip(c.id, { hero: e.target.value })} /></div></div><p className={c.error ? 'field-error' : 'field-hint'} role={c.error ? 'alert' : undefined}>{c.error || (c.duration ? `${c.file.name} · ${formatTime(c.duration)}` : 'Checking this recording…')}</p></article>)}</div>
              {review.clips.length < 5 && <button className="add-perspective" onClick={choose} onDragOver={e => e.preventDefault()} onDrop={drop}><Plus size={16} />Add another perspective</button>}
              <div className="form-actions"><span className="field-hint">Same fight. Different players.</span><button className="primary-button" disabled={!review.ready} onClick={() => review.setStep('context')}>Continue <ArrowRight size={17} /></button></div>
            </>}
          </>}
          {view === 'context' && <form onSubmit={e => { e.preventDefault(); void review.analyze(); }}>
            <label htmlFor="question">What are we looking at?</label><textarea id="question" rows={2} required maxLength={1000} value={review.question} onChange={e => review.setQuestion(e.target.value)} />
            <div className="question-chips">{(review.team ? ['Where did our coordination break down?', 'What could we each do better?'] : ['Did I push too early?', 'Was that ult worth it?']).map(q => <button type="button" key={q} onClick={() => review.setQuestion(q)}>{q}</button>)}</div>
            <label htmlFor="context">Anything else? <span>optional</span></label><textarea id="context" rows={3} maxLength={2000} placeholder="The plan, the panic, the missing context…" value={review.context} onChange={e => review.setContext(e.target.value)} />
            {review.team && <label className="alignment-confirm"><input type="checkbox" checked={review.confirmed} onChange={e => review.setConfirmed(e.target.checked)} /><span>These are different players in the same fight, and every marker identifies the same moment.</span></label>}
            <div className="manual-notice"><strong>Manual review workflow</strong><p>{review.availability.message}</p><p>Submitting prepares evidence for a reviewer. A verdict appears only after the team completes and audits the analysis.</p>{!review.availability.ready && <button type="button" className="text-button" onClick={() => void review.checkConnection()}>Check connection again</button>}</div>
            <div className="form-actions"><button className="text-button" type="button" onClick={() => review.setStep('upload')}><ArrowLeft size={15} />Back</button><button className="primary-button" disabled={!review.ready || !review.question.trim() || !review.availability.ready || (review.team && !review.confirmed)}>Prepare review <ArrowRight size={17} /></button></div>
          </form>}
          {view === 'review' && <div className="working-state"><div className="working-mascot"><Mascot pose="examining" bob={review.job?.state !== 'awaiting_review'} /></div><div><span className="mini-label">{review.job?.state === 'awaiting_review' ? 'WAITING FOR A REVIEWER' : 'PREPARING YOUR CASE'}</span><h3>{review.job?.state === 'awaiting_review' ? 'The evidence is ready.' : 'Getting the footage together.'}</h3><p role="status" aria-live="polite">{review.job?.message ?? 'Creating your local review.'}</p><ol className="stage-list"><li className={review.job?.state === 'uploading' ? 'current' : 'done'}>Send recordings locally</li><li className={review.job?.state === 'preparing' ? 'current' : ''}>Align recordings and prepare frames {review.job && `(${review.job.prepared.length}/${review.job.total})`}</li><li className={review.job?.state === 'awaiting_review' ? 'current' : ''}>Manual inspection and independent audit</li></ol>{review.job?.state === 'awaiting_review' && <details className="operator-details"><summary>Reviewer handoff</summary><p>Review ID: <code>{review.job.id}</code></p><p>Open <code>.local/reviews/{review.job.id}/REVIEW.md</code> in the integrated project. This window checks for the published result automatically.</p></details>}<p className="field-hint">Closing this window cancels the local review. Your selected recordings remain available for an explicit retry.</p><button className="text-button" onClick={review.stopReview}><X size={14} />Cancel review</button></div></div>}
          {view === 'verdict' && review.report && <><Verdict report={review.report} clips={review.clips} onSeek={review.seek} onExport={review.exportReport} /><button className="text-button" onClick={review.editReview}><ArrowLeft size={15} />Start another review with these clips</button></>}
        </motion.section>
      </div>
    </ReviewDialog>
    {import.meta.env.DEV && <Agentation />}
  </MotionConfig>;
}
