// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useReview } from '../src/useReview';
import { inspectDuration } from '../src/video';
import { sharedInterval } from '../src/review-session';
import { validateReviewReport } from '../src/api/contracts';
vi.mock('../src/video', async original => ({ ...await original<typeof import('../src/video')>(), inspectDuration: vi.fn() }));
const job = { id:'testjob', state:'uploading', prepared:[], total:1, message:'Synthetic test', report:null };
const report = { verdict:'inconclusive', summary:'Synthetic test only', fightSummary:'No gameplay reviewed', confidence:{label:'low',rationale:'Synthetic'}, evidence:[], decisions:[], players:[{povId:'pov1',summary:'Unknown',status:'no_supported_mistake'}],coaching:[], limitations:['Synthetic test only'] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const file = (name: string) => new File(['test'],name,{type:'video/mp4'});
beforeEach(() => {
  vi.stubGlobal('fetch',vi.fn(async () => json({ready:true,message:'Manual test pipeline'})));
  URL.createObjectURL = vi.fn(f => `blob:${(f as File).name}`); URL.revokeObjectURL = vi.fn();
  vi.mocked(inspectDuration).mockResolvedValue(12);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function ready(count=1) {
  const hook=renderHook(()=>useReview());
  act(()=>hook.result.current.addFiles(Array.from({length:count},(_,i)=>file(`p${i}.mp4`))));
  await waitFor(()=>expect(hook.result.current.ready).toBe(true));
  await waitFor(()=>expect(hook.result.current.availability.ready).toBe(true));
  return hook;
}
describe('perspectives and alignment',()=>{
 it('switches modes automatically but preserves an edited question and stable IDs',async()=>{
  const {result}=await ready();
  expect(result.current.question).toBe('Was that my fault?');
  act(()=>result.current.addFiles([file('second.mp4')]));
  await waitFor(()=>expect(result.current.clips[1].duration).toBe(12));
  expect(result.current.question).toBe('Whose fault was it?');
  act(()=>result.current.setQuestion('Did we engage together?'));
  act(()=>result.current.removeClip('pov1'));
  expect(result.current.team).toBe(false);
  expect(result.current.clips[0].id).toBe('pov2');
  expect(result.current.question).toBe('Did we engage together?');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:p0.mp4');
 });
 it('reverts an untouched default, enforces five and rejects duplicates',async()=>{
  const {result}=await ready(2);
  act(()=>result.current.removeClip('pov2'));
  expect(result.current.question).toBe('Was that my fault?');
  act(()=>result.current.addFiles([result.current.clips[0].file]));
  expect(result.current.error).toContain('already selected');
  act(()=>result.current.addFiles(Array.from({length:5},(_,i)=>file(`extra${i}.mp4`))));
  expect(result.current.error).toContain('up to five');
  expect(result.current.clips).toHaveLength(1);
 });
 it('requires matching markers, resets confirmation on changes, and computes overlap',async()=>{
  const {result}=await ready(2);
  act(()=>result.current.updateClip('pov1',{anchor:2}));
  act(()=>result.current.updateClip('pov2',{anchor:5}));
  expect(result.current.interval).toEqual({duration:9,starts:[0,3]});
  await act(async()=>{await result.current.analyze();});
  expect(fetch).toHaveBeenCalledTimes(1); // health only; not confirmed
  act(()=>result.current.setConfirmed(true));
  act(()=>result.current.updateClip('pov2',{anchor:6}));
  expect(result.current.confirmed).toBe(false);
  expect(sharedInterval([{duration:12,anchor:NaN}])).toBeNull();
 });
});
describe('review lifecycle',()=>{
 it('cancels on close, retains inputs, and ignores a late upload response',async()=>{
  const {result}=await ready();
  let resolve!: (value:Response)=>void;
  vi.mocked(fetch).mockImplementation(async(path,options)=>{
   if(path==='/api/reviews')return json(job,201);
   if(options?.method==='PUT')return new Promise(r=>{resolve=r;});
   return json({...job,state:'cancelled'});
  });
  let pending!:Promise<void>;
  act(()=>{pending=result.current.analyze();});
  await waitFor(()=>expect(resolve).toBeDefined());
  act(()=>result.current.closeReview());
  expect(result.current.busy).toBe(false); expect(result.current.clips).toHaveLength(1);
  await act(async()=>{resolve(json({uploaded:'pov1'}));await pending;});
  expect(result.current.report).toBeNull();
  expect(result.current.notice).toContain('Review stopped');
 });
 it('accepts automatic reviewer stages and cancels an active observation',async()=>{
  const {result}=await ready();
  vi.mocked(fetch).mockImplementation(async(path,options)=>
   path==='/api/reviews'?json(job):String(path).endsWith('/start')?
   json({...job,state:'observing',message:'Inspecting actual frames.'}):options?.method==='DELETE'?
   json({...job,state:'cancelled'}):json({uploaded:'pov1'}));
  let pending!:Promise<void>;
  act(()=>{pending=result.current.analyze();});
  await waitFor(()=>expect(result.current.job?.state).toBe('observing'));
  act(()=>result.current.closeReview());
  await act(async()=>{await pending;});
  expect(result.current.busy).toBe(false);
  expect(result.current.clips).toHaveLength(1);
  expect(result.current.report).toBeNull();
 });
 it('retains footage after failure, retries explicitly and validates completed reports',async()=>{
  const {result}=await ready();
  vi.mocked(fetch).mockResolvedValueOnce(json({detail:'Synthetic failure'},503));
  await act(async()=>{await result.current.analyze();});
  expect(result.current.error).toBe('Synthetic failure'); expect(result.current.clips).toHaveLength(1);
  vi.mocked(fetch).mockImplementation(async(path)=>path==='/api/reviews'?json(job):String(path).endsWith('/start')?json({...job,state:'complete',report}):json({uploaded:'pov1'}));
  await act(async()=>{await result.current.analyze();});
  expect(result.current.report?.verdict).toBe('inconclusive');
 });
 it('seeks another perspective after its video loads',async()=>{
  const {result}=await ready(2);
  act(()=>result.current.setActiveId('pov1'));
  const video={currentTime:0,pause:vi.fn()}; Object.assign(result.current.videoRef,{current:video});
  act(()=>result.current.seek({povId:'pov2',start:4,end:5}));
  expect(result.current.activeId).toBe('pov2');
  act(()=>result.current.applySeek());
  expect(video.currentTime).toBe(4);expect(video.pause).toHaveBeenCalledOnce();
 });
});
it('rejects report links to an absent perspective or outside a recording',()=>{
 const clips=[{id:'pov1',duration:12}];
 for(const ref of [{povId:'pov2',start:1,end:2},{povId:'pov1',start:11,end:13},{povId:'pov1',start:2,end:1}]) {
  expect(()=>validateReviewReport({...report,evidence:[{observation:'Synthetic',refs:[ref]}]},clips)).toThrow();
 }
});
