'use client';

import { X } from 'lucide-react';
import React, { useCallback, useEffect, useRef } from 'react';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  children: React.ReactNode;
  footer?: React.ReactNode;
  closeOnEscape?: boolean;
  closeOnBackdrop?: boolean;
}

const sizeWidths: Record<string, string> = {
  sm: '480px',
  md: '640px',
  lg: '960px',
  xl: '1200px',
};

/**
 * Reusable modal — backdrop, focus trap, escape-to-close, scroll lock.
 * Ported from ``MARS-PaperPulse/frontend/components/core/Modal.tsx``.
 */
export default function Modal({
  open,
  onClose,
  title,
  size = 'md',
  children,
  footer,
  closeOnEscape = true,
  closeOnBackdrop = true,
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const trapFocus = useCallback((e: KeyboardEvent) => {
    if (e.key !== 'Tab' || !modalRef.current) return;
    const focusable = modalRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement;
    requestAnimationFrame(() => modalRef.current?.focus());

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && closeOnEscape) onClose();
      trapFocus(e);
    };
    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
      previousFocusRef.current?.focus();
    };
  }, [open, closeOnEscape, onClose, trapFocus]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: 50 }}
    >
      <div
        className="absolute inset-0 bg-black/60"
        onClick={closeOnBackdrop ? onClose : undefined}
        aria-hidden="true"
        style={{ backdropFilter: 'blur(6px)' }}
      />
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
        className="relative flex w-full flex-col rounded-2xl shadow-2xl outline-none"
        style={{
          maxWidth: sizeWidths[size],
          maxHeight: '90vh',
          backgroundColor: 'var(--mars-color-surface-raised)',
          border: '1px solid var(--mars-color-border)',
          zIndex: 51,
          boxShadow: '0 24px 64px -12px rgba(0,0,0,0.65)',
        }}
      >
        <div
          className="flex flex-shrink-0 items-center justify-between border-b px-6 py-4"
          style={{ borderColor: 'var(--mars-color-border)' }}
        >
          <h2
            id="modal-title"
            className="text-lg font-semibold"
            style={{ color: 'var(--mars-color-text)' }}
          >
            {title}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 transition-colors hover:bg-[var(--mars-color-bg-hover)]"
            style={{ color: 'var(--mars-color-text-tertiary)' }}
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">{children}</div>

        {footer && (
          <div
            className="flex flex-shrink-0 items-center justify-end gap-3 border-t px-6 py-4"
            style={{ borderColor: 'var(--mars-color-border)' }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
