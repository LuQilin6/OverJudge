import { useState } from 'react';
import { Agentation } from 'agentation';
import { motion, MotionConfig, useReducedMotion } from 'motion/react';
import { ArrowLeft, ArrowRight, Check, CircleHelp, FileVideo, Film, FolderOpen, Gavel, MessageSquareText, Plus, Upload, X } from 'lucide-react';
import { useReview } from './useReview';
import { formatTime } from './video';
import { ReplayScene } from './components/ReplayScene';
import { ReviewDialog } from './components/ReviewDialog';
import { ReviewProgress } from './components/ReviewProgress';
import { Verdict } from './components/Verdict';

export default function App() {
  const review = useReview();
  const [open, setOpen] = useState(false);
  const [annotationContainer, setAnnotationContainer] = useState<HTMLDialogElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const reduced = useReducedMotion();
  const view = review.busy ? 'review' : review.report ? 'verdict' : review.step;
  const heading = { upload: 'Court is in session.', context: 'Your defense, please.', review: 'The court’s review.', verdict: 'Here’s what the evidence says.' }[view];
  const subtitle = { upload: 'One Overwatch fight. Up to five views. Let’s open the case.', context: review.team ? 'Line up your evidence, then tell the court what happened.' : 'Tell your side. The footage gets a say, too.', review: review.availability.execution === 'manual' ? 'Follow preparation and the handoff to your reviewer.' : 'Follow your case from footage to a checked verdict. Each step updates as it happens.', verdict: 'A fair call, with the footage to back it up.' }[view];
  function drop(event: React.DragEvent) { event.preventDefault(); setDragging(false); review.addFiles(Array.from(event.dataTransfer.files)); }
  const choose = () => review.inputRef.current?.click();
  return <MotionConfig reducedMotion="user">
    <ReplayScene onOpen={() => setOpen(true)} hasClip={review.clips.length > 0} />
    <ReviewDialog open={open} onDialogElementChange={import.meta.env.DEV ? setAnnotationContainer : undefined} onClose={() => { review.closeReview(); setOpen(false); }} title={heading} subtitle={subtitle} pose={view === 'review' ? 'examining' : view === 'verdict' ? 'presenting' : 'greeting'} step={view}>
      <div className="review-mode" role="status"><span><FolderOpen size={17} aria-hidden="true" />Evidence on file</span><span>{review.clips.length} of 5 recordings attached</span></div>
      <ol className="flow-steps" aria-label="Case progress">{[
        { label: 'The evidence', detail: 'Upload your clips', Icon: FileVideo },
        { label: 'Your defense', detail: 'Tell your side', Icon: MessageSquareText },
        { label: view === 'verdict' ? 'The verdict' : 'Judge’s review', detail: 'Follow the evidence', Icon: Gavel },
      ].map(({ label, detail, Icon }, i) => {
        const current = view === 'upload' ? 0 : view === 'context' ? 1 : 2;
        return <li key={i} className={i === current ? 'current' : i < current ? 'complete' : ''} aria-current={i === current ? 'step' : undefined}>
          <span className="step-icon" aria-hidden="true">{i < current ? <Check size={18} /> : <Icon size={18} />}</span>
          <div><strong>{label}</strong><small>{detail}</small></div>
        </li>;
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
            <p className="privacy-note">Recordings are sent to this computer’s local pipeline when you submit. {review.availability.execution === 'manual' ? 'No automatic model call.' : 'Selected frames and your question are sent to OpenAI through your Codex login, using your Codex allowance.'} Local review files expire after 24 hours when the server next cleans up.</p>
          </>}
        </section>
        <motion.section className="flow-content" key={view} initial={reduced ? false : { opacity: 0, y: 7 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .22 }}>
          {view === 'upload' && <>
            {!review.clips.length ? <div className="evidence-intake">
              <section className="evidence-guide" aria-labelledby="evidence-guide-title">
                <p className="mini-label">FIRST, THE FOOTAGE</p>
                <h3 id="evidence-guide-title">Bring your POV.<br /> Call a witness.</h3>
                <p>Start with your own recording. Want a second angle? Add a teammate’s view, the player whose decision you’re questioning, or a witness to the action.</p>
                <p className="evidence-rule"><strong>One fight per case.</strong> Upload 1–5 clips of that same fight. With multiple views, you’ll mark a shared moment so we can compare them.</p>
                <span className="evidence-promise"><Gavel size={16} aria-hidden="true" />No guilty verdict without the evidence.</span>
              </section>
              <button className={`dropzone ${dragging ? 'dragging' : ''}`} onClick={choose} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
                <span className="exhibit-label" aria-hidden="true">EXHIBIT A</span>
                <span className="upload-illustration" aria-hidden="true"><FolderOpen size={42} /><span><Upload size={18} /></span></span>
                <strong>Submit your evidence.</strong><span>Drop gameplay clips here, or <b>browse files</b></span>
                <small>MP4 / WebM · 10–90 seconds per clip<br />Up to 200 MB each · Maximum 5 recordings</small>
              </button>
            </div> : <>
              <p className="upload-guidance">Label whose view each recording shows. Add another player or a witness from the <strong>same fight</strong>, or make your case with the evidence already attached.</p>
              <div className="perspective-list">{review.clips.map((c, i) => <article className={`perspective-card ${c.error ? 'invalid' : ''}`} key={c.id}><div className="perspective-card-head"><span className="mini-label">PERSPECTIVE {i + 1}</span><button className="icon-button" aria-label={`Remove ${c.label}`} onClick={() => review.removeClip(c.id)}><X size={16} /></button></div><label htmlFor={`label-${c.id}`}>Player name</label><input id={`label-${c.id}`} maxLength={60} value={c.label} onChange={e => review.updateClip(c.id, { label: e.target.value })} /><div className="player-fields"><div><label htmlFor={`role-${c.id}`}>Role <span>optional</span></label><select id={`role-${c.id}`} value={c.role} onChange={e => review.updateClip(c.id, { role: e.target.value })}><option value="">Not specified</option>{['Tank', 'Damage', 'Support', 'Not sure'].map(r => <option key={r}>{r}</option>)}</select></div><div><label htmlFor={`hero-${c.id}`}>Hero <span>optional</span></label><input id={`hero-${c.id}`} maxLength={100} placeholder="e.g. Ana" value={c.hero} onChange={e => review.updateClip(c.id, { hero: e.target.value })} /></div></div><p className={c.error ? 'field-error' : 'field-hint'} role={c.error ? 'alert' : undefined}>{c.error || (c.duration ? `${c.file.name} · ${formatTime(c.duration)}` : 'Checking this recording…')}</p></article>)}</div>
              {review.clips.length < 5 && <button className="add-perspective" onClick={choose} onDragOver={e => e.preventDefault()} onDrop={drop}><Plus size={16} />Add another perspective</button>}
              <div className="form-actions"><span className="field-hint">{review.ready ? 'Evidence attached. Ready to tell your side?' : 'Checking your evidence…'}</span><button className="primary-button" disabled={!review.ready} onClick={() => review.setStep('context')}>Make your case <ArrowRight size={17} /></button></div>
            </>}
          </>}
          {view === 'context' && <form onSubmit={e => { e.preventDefault(); void review.analyze(); }}>
            <label htmlFor="question">What’s your objection?</label><p id="question-help" className="defense-help">Ask about a decision, a position, or the moment it all went sideways. The judge will check your question against the footage.</p><textarea id="question" aria-describedby="question-help" rows={2} required maxLength={1000} value={review.question} onChange={e => review.setQuestion(e.target.value)} />
            <div className="question-chips">{(review.team ? ['Where did our coordination break down?', 'What could we each do better?'] : ['Did I push too early?', 'Was that ult worth it?']).map(q => <button type="button" key={q} onClick={() => review.setQuestion(q)}>{q}</button>)}</div>
            <label htmlFor="context">Anything the court should know? <span>optional</span></label><textarea id="context" rows={3} maxLength={2000} placeholder="Your plan, what your team called, or what happened just before the clip…" value={review.context} onChange={e => review.setContext(e.target.value)} />
            {review.team && <label className="alignment-confirm"><input type="checkbox" checked={review.confirmed} onChange={e => review.setConfirmed(e.target.checked)} /><span>These are different players in the same fight, and every marker identifies the same moment.</span></label>}
            <div className="manual-notice"><strong>{review.availability.execution === 'manual' ? 'Manual review workflow' : 'Review with your Codex login'}</strong><p>{review.availability.message}</p><p>{review.availability.execution === 'manual' ? 'Submitting prepares evidence for a reviewer.' : 'Reviewing starts automatic Codex analysis and a separate AI evidence check. This is not a human audit, and fast events between sampled frames may be missed.'}</p>{!review.availability.ready && <button type="button" className="text-button" onClick={() => void review.checkConnection()}>Check connection again</button>}</div>
            <div className="form-actions"><button className="text-button" type="button" onClick={() => review.setStep('upload')}><ArrowLeft size={15} />Back</button><button className="primary-button" disabled={!review.ready || !review.question.trim() || !review.availability.ready || (review.team && !review.confirmed)}>{review.availability.execution === 'manual' ? 'Prepare review' : 'Call the judge'} <ArrowRight size={17} /></button></div>
          </form>}
          {view === 'review' && <ReviewProgress job={review.job} execution={review.availability.execution} onCancel={review.stopReview} />}
          {view === 'verdict' && review.report && <><Verdict report={review.report} clips={review.clips} onSeek={review.seek} onExport={review.exportReport} /><button className="text-button" onClick={review.editReview}><ArrowLeft size={15} />Start another review with these clips</button></>}
        </motion.section>
      </div>
    </ReviewDialog>
    {import.meta.env.DEV && <Agentation portalContainer={annotationContainer} />}
  </MotionConfig>;
}
