'use client';

import { ButtonHTMLAttributes, CSSProperties, forwardRef } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const sizeClass: Record<Size, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3.5 py-1.5 text-sm',
  lg: 'px-5 py-2.5 text-sm',
};

const variantStyle = (variant: Variant, disabled: boolean): CSSProperties => {
  if (disabled) {
    return {
      background: 'var(--mars-color-surface-overlay)',
      color: 'var(--mars-color-text-disabled)',
      border: '1px solid var(--mars-color-border)',
    };
  }
  switch (variant) {
    case 'primary':
      return {
        background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
        color: '#fff',
        border: '1px solid rgba(139,92,246,0.40)',
        boxShadow: '0 4px 14px rgba(99, 102, 241, 0.40), inset 0 1px 0 rgba(255,255,255,0.18)',
      };
    case 'secondary':
      return {
        background: 'var(--mars-color-surface-overlay)',
        color: 'var(--mars-color-text)',
        border: '1px solid var(--mars-color-border)',
      };
    case 'ghost':
      return {
        background: 'transparent',
        color: 'var(--mars-color-text-secondary)',
        border: '1px solid transparent',
      };
    case 'danger':
      return {
        background: 'linear-gradient(135deg, #ef4444, #dc2626)',
        color: '#fff',
        border: '1px solid rgba(239,68,68,0.4)',
        boxShadow: '0 4px 14px rgba(239, 68, 68, 0.30)',
      };
  }
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', size = 'md', loading, className = '', children, disabled, style, ...rest },
  ref,
) {
  const isDisabled = !!(disabled || loading);
  const styleVariant = variantStyle(variant, isDisabled);
  return (
    <button
      ref={ref}
      className={`mars-shimmer-btn inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-all duration-150 disabled:cursor-not-allowed hover:enabled:scale-[1.02] active:enabled:scale-[0.98] ${sizeClass[size]} ${className}`}
      disabled={isDisabled}
      style={{ ...styleVariant, ...(style || {}) }}
      {...rest}
    >
      {loading && (
        <span
          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'currentColor', borderTopColor: 'transparent' }}
        />
      )}
      {children}
    </button>
  );
});
