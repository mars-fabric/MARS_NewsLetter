'use client';

import type { ProviderStatusType } from '@/types/providers';

const STATUS_CONFIG: Record<
  ProviderStatusType,
  { label: string; bg: string; text: string; dot: string }
> = {
  validated: { label: 'Valid', bg: 'rgba(34,197,94,0.12)', text: '#22c55e', dot: '#22c55e' },
  configured: { label: 'Configured', bg: 'rgba(59,130,246,0.12)', text: '#3b82f6', dot: '#3b82f6' },
  invalid: { label: 'Invalid', bg: 'rgba(239,68,68,0.12)', text: '#ef4444', dot: '#ef4444' },
  not_configured: { label: 'Not Configured', bg: 'rgba(156,163,175,0.12)', text: '#9ca3af', dot: '#9ca3af' },
  error: { label: 'Error', bg: 'rgba(245,158,11,0.12)', text: '#f59e0b', dot: '#f59e0b' },
};

export default function ProviderStatusBadge({ status }: { status: ProviderStatusType }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.not_configured;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ backgroundColor: cfg.bg, color: cfg.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: cfg.dot }} />
      {cfg.label}
    </span>
  );
}
