import { z } from 'zod';
const ref = z.object({ povId: z.string(), start: z.number().finite().nonnegative(), end: z.number().finite().positive() });
export type EvidenceRef = z.infer<typeof ref>;
export const reviewReportSchema = z.object({
  verdict: z.enum(['inconclusive', 'shared', 'supported']), summary: z.string(), fightSummary: z.string(),
  confidence: z.object({ label: z.enum(['low', 'medium', 'high']), rationale: z.string() }),
  evidence: z.array(z.object({ observation: z.string(), refs: z.array(ref) })),
  decisions: z.array(z.object({ pov_id: z.string(), level: z.enum(['primary', 'secondary', 'shared', 'not_established']), claim: z.string(), player_information: z.string(), alternative_action: z.string(), causal_reasoning: z.string(), alternative_explanation: z.string(), refs: z.array(ref) })),
  players: z.array(z.object({ povId: z.string(), summary: z.string(), status: z.enum(['findings', 'no_supported_mistake']), responsibilityPercent: z.number().optional() })),
  coaching: z.array(z.object({ povIds: z.array(z.string()), lesson: z.string(), refs: z.array(ref) })),
  limitations: z.array(z.string()).min(1),
});
export type ReviewReport = z.infer<typeof reviewReportSchema>;
export const jobSchema = z.object({ id: z.string(), state: z.enum(['uploading', 'preparing', 'awaiting_review', 'queued', 'observing', 'comparing', 'judging', 'auditing', 'complete', 'failed', 'cancelled']), message: z.string(), prepared: z.array(z.string()), total: z.number(), report: reviewReportSchema.nullable() });
export type ReviewJob = z.infer<typeof jobSchema>;
export function validateReviewReport(value: unknown, clips: { id: string; duration: number | null }[]) {
  const report = reviewReportSchema.parse(value);
  const ids = new Set(clips.map(c => c.id));
  const refs = [...report.evidence.flatMap(e => e.refs), ...report.decisions.flatMap(d => d.refs), ...report.coaching.flatMap(c => c.refs)];
  for (const r of refs) {
    const clip = clips.find(c => c.id === r.povId);
    if (!clip?.duration || r.start >= r.end || r.end > clip.duration + .05) throw new Error('The report references unavailable footage. Ask the reviewer to correct its evidence.');
  }
  if (report.players.length !== ids.size || new Set(report.players.map(p => p.povId)).size !== ids.size || report.players.some(p => !ids.has(p.povId)) || report.decisions.some(d => !ids.has(d.pov_id) || !d.refs.length) || report.coaching.some(c => !c.refs.length || c.povIds.some(id => !ids.has(id)))) throw new Error('The report does not match the selected perspectives.');
  return report;
}
