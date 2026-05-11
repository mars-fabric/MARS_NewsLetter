'use client';

import { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  accent?: string;
  glow?: boolean;
}

const padding = {
  none: '',
  sm: 'p-3',
  md: 'p-5',
  lg: 'p-7',
};

export function Card({
  children,
  padding: p = 'md',
  accent,
  glow = false,
  className = '',
  style,
  ...rest
}: CardProps) {
  return (
    <div
      className={`relative overflow-hidden rounded-xl border ${padding[p]} ${className}`}
      style={{
        backgroundColor: 'var(--mars-color-surface-raised)',
        borderColor: 'var(--mars-color-border)',
        boxShadow: glow
          ? '0 8px 32px -8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04)'
          : '0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.03)',
        ...(style || {}),
      }}
      {...rest}
    >
      {accent && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }}
        />
      )}
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <h3
      className={`text-sm font-semibold tracking-tight ${className}`}
      style={{ color: 'var(--mars-color-text)' }}
    >
      {children}
    </h3>
  );
}

export function CardSubtitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <p className={`text-xs leading-relaxed ${className}`} style={{ color: 'var(--mars-color-text-secondary)' }}>
      {children}
    </p>
  );
}
