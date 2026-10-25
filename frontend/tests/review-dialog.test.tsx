// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ReviewDialog } from '../src/components/ReviewDialog';
vi.mock('../src/components/Mascot', () => ({ Mascot: () => null }));
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('wraps focus past collapsed connection controls and includes them when expanded', () => {
  const onClose = vi.fn();
  render(<ReviewDialog open onClose={onClose} title="Review" subtitle="Test window" pose="idle" step="upload">
    <button>Upload</button><details><summary>Connection</summary><button>Hidden sign-in</button></details>
  </ReviewDialog>);
  const close = screen.getByRole('button', { name: 'Close replay window' });
  const summary = screen.getByText('Connection');
  close.focus(); fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(summary);
  fireEvent.keyDown(summary, { key: 'Tab' });
  expect(document.activeElement).toBe(close);
  summary.closest('details')!.open = true;
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Hidden sign-in' }));
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
  expect(onClose).toHaveBeenCalledOnce();
});
