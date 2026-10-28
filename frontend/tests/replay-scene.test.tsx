// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ReplayScene } from '../src/components/ReplayScene';
vi.mock('../src/components/Mascot', () => ({ Mascot: ({ pose }: { pose: string }) => <span data-testid="scene-pose">{pose}</span> }));
afterEach(cleanup);

it('restores idle after opening a review and returning focus, then allows a fresh greeting', () => {
  const onOpen = vi.fn();
  render(<ReplayScene onOpen={onOpen} hasClip={false} />);
  const dog = screen.getByRole('button', { name: 'Talk to the dog referee' });
  fireEvent.focus(dog);
  expect(screen.getByTestId('scene-pose').textContent).toBe('greeting');
  fireEvent.click(dog);
  expect(onOpen).toHaveBeenCalledOnce();
  expect(screen.getByTestId('scene-pose').textContent).toBe('idle');
  fireEvent.blur(dog);
  fireEvent.focus(dog);
  expect(screen.getByTestId('scene-pose').textContent).toBe('idle');
  fireEvent.blur(dog);
  fireEvent.focus(dog);
  expect(screen.getByTestId('scene-pose').textContent).toBe('greeting');
  fireEvent.pointerLeave(dog);
  expect(screen.getByTestId('scene-pose').textContent).toBe('idle');
});
