import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { Mascot, type MascotPose } from './Mascot';

export function ReviewDialog({ open, onClose, title, subtitle, pose, step, children, onDialogElementChange }: {
  open: boolean; onClose: () => void; title: string; subtitle: string; pose: MascotPose; step: string; children: ReactNode;
  onDialogElementChange?: (element: HTMLDialogElement | null) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
    if (!open) return;
    // Move development overlays only after the dialog enters the browser's top layer.
    onDialogElementChange?.(element);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    heading.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      onDialogElementChange?.(null);
    };
  }, [open, onDialogElementChange]);
  useEffect(() => {
    if (open) { heading.current?.focus(); if (body.current) body.current.scrollTop = 0; }
  }, [step, open]);
  return <dialog ref={dialog} className="review-dialog" aria-labelledby="dialog-title" aria-describedby="dialog-subtitle"
    onCancel={e => { e.preventDefault(); onClose(); }} onKeyDown={e => {
      if (e.key !== 'Tab') return;
      const focusable = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled):not([tabindex="-1"]), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]'))
        .filter(element => {
          const collapsed = element.closest('details:not([open])');
          // Chromium can retain layout rectangles for content inside closed details.
          return element.getClientRects().length > 0 && !element.closest('[hidden]') &&
            (!collapsed || element === collapsed.querySelector(':scope > summary'));
        });
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) {
        e.preventDefault(); last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first?.focus();
      }
    }} onClick={e => { if (e.target === e.currentTarget) {
      const box = e.currentTarget.getBoundingClientRect();
      if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) onClose();
    } }}>
    <div className="case-file-cover" aria-hidden="true"><span>OVERWATCH REPLAY COURT</span><strong>Case file.</strong><p>Let the footage speak.</p><span className="cover-stamp">FOR REVIEW</span></div>
    <div className="case-binding" aria-hidden="true"><span>REPLAY COURT</span></div>
    <header className="dialog-header"><div className="dialog-portrait"><Mascot pose={pose} /></div>
      <div><p className="eyebrow">OVERWATCH REPLAY COURT <span aria-hidden="true">/</span> CASE FILE</p><h2 id="dialog-title" ref={heading} tabIndex={-1}>{title}</h2><p id="dialog-subtitle">{subtitle}</p></div>
      <button className="icon-button close-dialog" aria-label="Close replay window" onClick={onClose}><X size={20} /></button>
    </header>
    <div className="dialog-body" ref={body}>{children}</div>
    <footer className="dialog-footer"><p>A second opinion, not the final word. AI reviews sampled frames, which can miss fast action. Audio isn’t analyzed.</p></footer>
  </dialog>;
}
