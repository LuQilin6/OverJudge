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
it('exposes the opened dialog to overlays and releases it on close and unmount', () => {
  const onDialogElementChange = vi.fn((element: HTMLDialogElement | null) => {
    if (element) expect(element.open).toBe(true);
  });
  const props = { onClose: vi.fn(), title: 'Review', subtitle: 'Test window', pose: 'idle' as const, step: 'upload', onDialogElementChange };
  const { rerender, unmount } = render(<ReviewDialog {...props} open={false}><button>Upload</button></ReviewDialog>);
  expect(onDialogElementChange).not.toHaveBeenCalled();
  rerender(<ReviewDialog {...props} open><button>Upload</button></ReviewDialog>);
  const dialog = screen.getByRole('dialog');
  expect(onDialogElementChange).toHaveBeenLastCalledWith(dialog);
  rerender(<ReviewDialog {...props} open step="context"><button>Review</button></ReviewDialog>);
  expect(onDialogElementChange).toHaveBeenCalledTimes(1);
  rerender(<ReviewDialog {...props} open={false}><button>Upload</button></ReviewDialog>);
  expect(onDialogElementChange).toHaveBeenLastCalledWith(null);
  rerender(<ReviewDialog {...props} open><button>Upload</button></ReviewDialog>);
  expect(onDialogElementChange).toHaveBeenLastCalledWith(dialog);
  unmount();
  expect(onDialogElementChange).toHaveBeenLastCalledWith(null);
});
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
