export const SINGLE_QUESTION = 'Was that my fault?';
export const TEAM_QUESTION = 'Whose fault was it?';
export type Perspective = { id: string; file: File; url: string; duration: number | null; error: string; label: string; role: string; hero: string; anchor: number };
export function defaultQuestion(count: number) { return count > 1 ? TEAM_QUESTION : SINGLE_QUESTION; }
export function sharedInterval(clips: Pick<Perspective, 'anchor' | 'duration'>[]) {
  if (!clips.length || clips.some(c => !c.duration || !Number.isFinite(c.anchor) || c.anchor < 0 || c.anchor >= c.duration)) return null;
  const before = Math.min(...clips.map(c => c.anchor));
  const after = Math.min(...clips.map(c => c.duration! - c.anchor));
  return { duration: before + after, starts: clips.map(c => c.anchor - before) };
}
