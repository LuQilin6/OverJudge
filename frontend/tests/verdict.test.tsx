// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Verdict } from '../src/components/Verdict';
import { examplePlayers, exampleReport } from '../src/data/example-report';
afterEach(cleanup);
it('seeks the exact evidence reference and exports the report', () => {
  const onSeek = vi.fn(), onExport = vi.fn();
  render(<Verdict report={exampleReport} clips={examplePlayers} onSeek={onSeek} onExport={onExport} />);
  fireEvent.click(screen.getByRole('button', { name: 'View ROXY at 00:10' }));
  expect(onSeek).toHaveBeenCalledWith({ povId: 'tank', start: 10, end: 11 });
  fireEvent.click(screen.getByRole('button', { name: /Download report/ }));
  expect(onExport).toHaveBeenCalledOnce();
});
it('keeps reconstruction previews separate from final judgments and playable evidence', () => {
  render(<Verdict report={exampleReport} clips={examplePlayers} preview onSeek={vi.fn()} onExport={vi.fn()} />);
  expect(screen.queryByRole('button', { name: /^View ROXY/ })).toBeNull();
  expect(screen.getByText('The fight reconstructed. Judgment pending.')).toBeTruthy();
  expect(screen.getAllByText('Final judgment not supplied')).toHaveLength(5);
});

it('shows model estimates unchanged, ranked by contribution, and retains evidence seeking', () => {
  const report = { ...exampleReport, players: exampleReport.players.map((p, i) => ({ ...p, responsibilityPercent: [12, 73, 8, 4, 2][i] })) };
  render(<Verdict report={report} clips={examplePlayers} onSeek={vi.fn()} onExport={vi.fn()} />);
  expect(screen.getByText('Who takes the blame?')).toBeTruthy();
  const list = document.querySelector('.responsibility-list')!;
  expect(list.firstElementChild?.textContent).toContain('73%');
  expect(screen.getByText('12%')).toBeTruthy();
});
it('shows a single player estimate without forcing 100 percent', () => {
  const report = { ...exampleReport, players: [{ ...exampleReport.players[0], responsibilityPercent: 35 }] };
  render(<Verdict report={report} clips={examplePlayers.slice(0, 1)} onSeek={vi.fn()} onExport={vi.fn()} />);
  expect(screen.getByText('How much blame is on you?')).toBeTruthy();
  expect(screen.getByText('35%')).toBeTruthy();
  expect(screen.queryByText('100%')).toBeNull();
});
