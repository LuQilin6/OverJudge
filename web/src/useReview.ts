import { useEffect, useRef, useState } from 'react';
import { jobSchema, validateReviewReport, type EvidenceRef, type ReviewJob, type ReviewReport } from '../shared/reviews';
import { checkFile, inspectDuration } from './video';
import { defaultQuestion, sharedInterval, type Perspective } from './review-session';

async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(path, { ...options, signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(120_000)]) : AbortSignal.timeout(15_000) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'The local review server could not complete this step. Please retry.');
  return data;
}
function delay(signal: AbortSignal) { return new Promise<void>((resolve, reject) => {
  const done = () => { signal.removeEventListener('abort', stop); resolve(); };
  const timer = setTimeout(done, 3000);
  const stop = () => { clearTimeout(timer); signal.removeEventListener('abort', stop); reject(new DOMException('Cancelled', 'AbortError')); };
  signal.addEventListener('abort', stop, { once: true });
  if (signal.aborted) stop();
}); }
export function useReview() {
  const [clips, setClips] = useState<Perspective[]>([]);
  const clipsRef = useRef<Perspective[]>([]);
  const [activeId, setActiveId] = useState('');
  const [step, setStep] = useState<'upload' | 'context'>('upload');
  const [question, updateQuestion] = useState(defaultQuestion(1));
  const dirtyQuestion = useRef(false);
  const [context, setContext] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<ReviewJob | null>(null);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [availability, setAvailability] = useState({ ready: false, execution: 'codex', message: 'Checking the local review pipeline…' });
  const videoRef = useRef<HTMLVideoElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reportInput = useRef<unknown>(null);
  const abort = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const jobId = useRef('');
  const pendingSeek = useRef<EvidenceRef | null>(null);
  const inspections = useRef(new Map<string, AbortController>());
  const clip = clips.find(c => c.id === activeId) ?? clips[0] ?? null;
  const team = clips.length > 1;
  const interval = sharedInterval(clips);
  const ready = clips.length > 0 && clips.every(c => c.duration && !c.error && c.label.trim()) && Boolean(interval && interval.duration >= 2);

  async function checkConnection() {
    try { setAvailability(await request('/api/health')); }
    catch { setAvailability({ ready: false, execution: 'codex', message: 'The local pipeline is unavailable. Start the server, then check again.' }); }
  }
  useEffect(() => { void checkConnection(); return () => {
    generation.current++; abort.current?.abort();
    if (jobId.current) void fetch(`/api/reviews/${jobId.current}`, { method: 'DELETE', keepalive: true }).catch(() => {});
    for (const controller of inspections.current.values()) controller.abort();
    for (const c of clipsRef.current) URL.revokeObjectURL(c.url);
  }; }, []);
  function assign(next: Perspective[]) {
    clipsRef.current = next; setClips(next);
    if (!dirtyQuestion.current) updateQuestion(defaultQuestion(next.length));
  }
  function setQuestion(text: string) { dirtyQuestion.current = true; updateQuestion(text); }
  function cancel() {
    generation.current++; abort.current?.abort(); abort.current = null;
    if (jobId.current) void fetch(`/api/reviews/${jobId.current}`, { method: 'DELETE', keepalive: true }).catch(() => {});
    jobId.current = ''; setBusy(false); setJob(null);
  }
  function changed() { cancel(); setReport(null); setNotice(''); setError(''); setConfirmed(false); }
  function addFiles(files: File[]) {
    if (!files.length) return;
    try {
      if (files.length + clipsRef.current.length > 5) throw new Error('Choose up to five perspectives. Remove a recording before adding another.');
      files.forEach(checkFile);
      const keys = [...clipsRef.current.map(c => c.file), ...files].map(f => `${f.name}:${f.size}:${f.lastModified}`);
      if (new Set(keys).size !== keys.length) throw new Error('That recording is already selected. Add a different player’s perspective.');
    } catch (e) { setError((e as Error).message); return; }
    changed(); setStep('upload');
    const next = [...clipsRef.current]; const added: Perspective[] = [];
    for (const file of files) {
      const id = Array.from({ length: 5 }, (_, i) => `pov${i + 1}`).find(id => !next.some(c => c.id === id))!;
      const item = { id, file, url: URL.createObjectURL(file), duration: null, error: '', label: next.length ? `Player ${next.length + 1}` : 'Me', role: '', hero: '', anchor: 0 };
      next.push(item); added.push(item);
    }
    assign(next); setActiveId(added[0].id);
    if (next.length > 1 && next.length - added.length <= 1) setNotice('Another perspective! I’ll compare the available views of this fight.');
    for (const item of added) {
      const controller = new AbortController(); inspections.current.set(item.id, controller);
      void inspectDuration(item.url, controller.signal).then(duration => {
        if (clipsRef.current.some(c => c.url === item.url)) assign(clipsRef.current.map(c => c.url === item.url ? { ...c, duration } : c));
      }).catch(e => {
        if (!controller.signal.aborted) assign(clipsRef.current.map(c => c.url === item.url ? { ...c, error: (e as Error).message } : c));
      }).finally(() => { if (inspections.current.get(item.id) === controller) inspections.current.delete(item.id); });
    }
  }
  function removeClip(id: string) {
    changed(); const old = clipsRef.current.find(c => c.id === id); inspections.current.get(id)?.abort();
    if (old) URL.revokeObjectURL(old.url);
    const next = clipsRef.current.filter(c => c.id !== id);
    if (next.length === 1) next[0] = { ...next[0], anchor: 0 };
    assign(next); if (activeId === id) setActiveId(next[0]?.id ?? '');
    if (!next.length) setStep('upload');
  }
  function updateClip(id: string, values: Partial<Pick<Perspective, 'label' | 'role' | 'hero' | 'anchor'>>) {
    changed(); assign(clipsRef.current.map(c => c.id === id ? { ...c, ...values } : c));
  }
  function stopReview() { cancel(); setStep('context'); setNotice('Review stopped. Your recordings and answers are still here. Start again when you’re ready.'); }
  function closeReview() { videoRef.current?.pause(); if (busy) stopReview(); }
  function seek(ref: EvidenceRef) {
    pendingSeek.current = ref; setActiveId(ref.povId);
    if (clip?.id === ref.povId) applySeek();
  }
  function applySeek() {
    const ref = pendingSeek.current;
    if (ref && videoRef.current) { videoRef.current.currentTime = ref.start; videoRef.current.pause(); pendingSeek.current = null; }
  }
  async function analyze() {
    if (!ready || !question.trim() || busy || !availability.ready || (team && !confirmed)) return;
    cancel(); const version = generation.current; const controller = new AbortController(); abort.current = controller;
    const signal = controller.signal; const snapshot = clipsRef.current.map(c => ({ ...c }));
    const spec = { clips: snapshot.map(c => ({ id: c.id, name: c.file.name, label: c.label.trim(), hero: c.hero.trim(), role: c.role, duration: c.duration, anchor: c.anchor, size: c.file.size })), question: question.trim(), context: context.trim(), alignmentConfirmed: confirmed };
    reportInput.current = spec; setBusy(true); setReport(null); setError(''); setNotice('');
    let createdId = '';
    try {
      const created = jobSchema.parse(await request('/api/reviews', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec), signal }));
      createdId = created.id;
      if (signal.aborted || generation.current !== version) { void fetch(`/api/reviews/${created.id}`, { method: 'DELETE' }); return; }
      jobId.current = created.id; setJob(created);
      for (const [i, c] of snapshot.entries()) {
        setJob({ ...created, message: `Sending ${c.label} to the local pipeline (${i + 1} of ${snapshot.length}).` });
        await request(`/api/reviews/${created.id}/clips/${c.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: c.file, signal });
      }
      let current = jobSchema.parse(await request(`/api/reviews/${created.id}/start`, { method: 'POST', signal }));
      while (!signal.aborted && generation.current === version) {
        setJob(current);
        if (current.state === 'failed') { createdId = ''; throw new Error(current.message); }
        if (current.state === 'cancelled') throw new Error(current.message);
        if (current.state === 'complete') {
          const result = validateReviewReport(current.report, snapshot);
          setReport(result); return;
        }
        await delay(signal);
        current = jobSchema.parse(await request(`/api/reviews/${created.id}`, { signal }));
      }
    } catch (e) {
      if (createdId) void fetch(`/api/reviews/${createdId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
      if (version === generation.current && !signal.aborted) setError(e instanceof TypeError ? 'Could not reach the local server. Your recordings are retained; retry when it is running.' : (e as Error).message);
    } finally {
      if (version === generation.current) { setBusy(false); abort.current = null; }
    }
  }
  function exportReport() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ input: reportInput.current, report }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'overjudge-review.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function editReview() { cancel(); setReport(null); setStep('context'); }
  return { clips, clip, activeId, setActiveId, step, setStep, team, question, setQuestion, context, setContext, confirmed, setConfirmed, interval, ready, job, report, busy, error, setError, notice, availability, checkConnection, videoRef, inputRef, addFiles, removeClip, updateClip, analyze, stopReview, closeReview, seek, applySeek, exportReport, editReview };
}
export type ReviewController = ReturnType<typeof useReview>;
