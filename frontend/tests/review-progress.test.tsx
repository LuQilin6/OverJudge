// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getReviewProgress, ReviewProgress } from '../src/components/ReviewProgress';
import type { ReviewJob } from '../src/api/contracts';
vi.mock('../src/components/Mascot', () => ({ Mascot: () => null }));
const job = (state: ReviewJob['state'], extra: Partial<ReviewJob> = {}): ReviewJob => ({ id: 'mock-review', state, message: 'Mock backend stage update', prepared: [], total: 2, report: null, ...extra });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('tracks all actual stages, including initial creation and final validation', () => {
  expect(getReviewProgress(undefined, false).current).toBe(0);
  const states: ReviewJob['state'][] = ['uploading','preparing','observing','comparing','judging','auditing','awaiting_review'];
  states.forEach((state,index) => expect(getReviewProgress(state,false).current).toBe(index));
  expect(getReviewProgress('complete',false).current).toBe(7);
  expect(getReviewProgress('failed',false).current).toBe(-1);
  expect(getReviewProgress('cancelled',false).current).toBe(-1);
});
it('shows real preparation counts, then completes only earlier stages', () => {
  const { rerender } = render(<ReviewProgress job={job('preparing',{prepared:['pov1']})} execution="codex" onCancel={vi.fn()} />);
  expect(screen.getByRole('progressbar').getAttribute('value')).toBe('1');
  expect(screen.getByRole('progressbar').getAttribute('max')).toBe('2');
  expect(screen.getByText('1 of 2 recordings prepared')).toBeTruthy();
  expect(within(screen.getByRole('list')).getAllByText('Complete')).toHaveLength(1);
  rerender(<ReviewProgress job={job('auditing')} execution="codex" onCancel={vi.fn()} />);
  const rows = within(screen.getByRole('list')).getAllByRole('listitem');
  expect(rows.filter(row => row.getAttribute('aria-current') === 'step')).toHaveLength(1);
  expect(rows[5].getAttribute('aria-current')).toBe('step');
  expect(within(rows[5]).getByText('In progress')).toBeTruthy();
  expect(within(rows[6]).getByText('Not started')).toBeTruthy();
  expect(within(screen.getByRole('list')).getAllByText('Complete')).toHaveLength(5);
  expect(screen.queryByRole('progressbar')).toBeNull();
});
it('treats a queued review as waiting, not active inspection', () => {
  render(<ReviewProgress job={job('queued')} execution="codex" onCancel={vi.fn()} />);
  expect(screen.getByRole('heading',{name:'Waiting for the judge.'})).toBeTruthy();
  expect(within(screen.getByRole('list')).queryByText('In progress')).toBeNull();
  expect(screen.getByText('Queued for the local reviewer; inspection has not started yet.')).toBeTruthy();
});
it('distinguishes manual handoff from automatic report validation', () => {
  const {rerender} = render(<ReviewProgress job={job('awaiting_review')} execution="manual" onCancel={vi.fn()} />);
  expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(3);
  expect(screen.getByText('Reviewer handoff')).toBeTruthy();
  expect(screen.getByText(/No AI model is running automatically/)).toBeTruthy();
  rerender(<ReviewProgress job={job('awaiting_review')} execution="codex" onCancel={vi.fn()} />);
  expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(7);
  expect(screen.queryByText('Reviewer handoff')).toBeNull();
  expect(screen.getByRole('heading',{name:'Validate the case file'})).toBeTruthy();
});
it('counts elapsed time without advancing stages and clears its clock on unmount', () => {
  vi.useFakeTimers();
  const onCancel=vi.fn();
  const {unmount}=render(<ReviewProgress job={job('observing')} execution="codex" onCancel={onCancel} />);
  act(()=>{vi.advanceTimersByTime(65_000);});
  expect(screen.getByLabelText('Elapsed time 01:05')).toBeTruthy();
  expect(screen.getByText('STEP 3 OF 7')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Cancel review'}));
  expect(onCancel).toHaveBeenCalledOnce();
  unmount(); expect(vi.getTimerCount()).toBe(0);
});
