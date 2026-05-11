'use client';

import { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes, forwardRef } from 'react';

const baseClass =
  'w-full rounded-lg px-3.5 py-2.5 text-sm transition-all duration-150 outline-none mars-input';

const baseStyle = {
  backgroundColor: 'var(--mars-color-surface-sunken)',
  color: 'var(--mars-color-text)',
  border: '1px solid var(--mars-color-border)',
  boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.25)',
} as const;

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className = '', style, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={`${baseClass} ${className}`}
        style={{ ...baseStyle, ...(style || {}) }}
        {...rest}
      />
    );
  },
);

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function TextArea({ className = '', style, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={`${baseClass} font-mono text-xs leading-5 ${className}`}
        style={{ ...baseStyle, ...(style || {}) }}
        {...rest}
      />
    );
  },
);

export function Label({
  htmlFor,
  children,
  hint,
}: {
  htmlFor?: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1.5 block text-[10.5px] font-bold uppercase tracking-[0.08em]"
      style={{ color: 'var(--mars-color-text-tertiary)' }}
    >
      {children}
      {hint && (
        <span className="ml-2 normal-case font-medium tracking-normal" style={{ color: 'var(--mars-color-text-disabled)' }}>
          — {hint}
        </span>
      )}
    </label>
  );
}
