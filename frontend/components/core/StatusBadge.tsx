'use client';

import { CSSProperties } from 'react';

import { StageStatus } from '@/types/newsletter';

interface BadgeStyle {
  label: string;
  color: string;
  bg: string;
  border: string;
}

const styles: Record<StageStatus, BadgeStyle> = {
  pending: {
    label: 'Pending',
    color: 'var(--mars-color-text-tertiary)',
    bg: 'var(--mars-color-surface-overlay)',
    border: 'var(--mars-color-border)',
  },
  running: {
    label: 'Running',
    color: 'var(--mars-color-warning)',
    bg: 'rgba(245, 158, 11, 0.15)',
    border: 'rgba(245, 158, 11, 0.35)',
  },
  completed: {
    label: 'Completed',
    color: 'var(--mars-color-success)',
    bg: 'rgba(34, 197, 94, 0.15)',
    border: 'rgba(34, 197, 94, 0.35)',
  },
  failed: {
    label: 'Failed',
    color: 'var(--mars-color-danger)',
    bg: 'rgba(239, 68, 68, 0.15)',
    border: 'rgba(239, 68, 68, 0.35)',
  },
};

export function StatusBadge({ status }: { status: StageStatus }) {
  const cfg = styles[status] ?? styles.pending;
  const style: CSSProperties = {
    color: cfg.color,
    backgroundColor: cfg.bg,
    borderColor: cfg.border,
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
        status === 'running' ? 'animate-pulse' : ''
      }`}
      style={style}
    >
      {status === 'running' && (
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cfg.color, boxShadow: `0 0 8px ${cfg.color}` }} />
      )}
      {cfg.label}
    </span>
  );
}
