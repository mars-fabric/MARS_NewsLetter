'use client';

import { Activity, Terminal } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { ConsoleLine } from '@/hooks/useNewsletterTask';

type LineKind = 'info' | 'warn' | 'err' | 'ok' | 'dim';

function classify(text: string): LineKind {
  const t = text.toLowerCase();
  if (/(error|traceback|failed|exception|fatal)/.test(t)) return 'err';
  if (/(warn|warning|⚠)/.test(t)) return 'warn';
  if (/(success|✓|completed|done|ok\b|finished)/.test(t)) return 'ok';
  if (/^(===|---|>>>|\s*$)/.test(text)) return 'dim';
  return 'info';
}

const LINE_COLOR: Record<LineKind, string> = {
  info: 'var(--mars-color-text)',
  warn: '#fbbf24',
  err: '#f87171',
  ok: '#4ade80',
  dim: 'var(--mars-color-text-tertiary)',
};

const LINE_BG: Record<LineKind, string> = {
  info: 'transparent',
  warn: 'rgba(251, 191, 36, 0.06)',
  err: 'rgba(248, 113, 113, 0.08)',
  ok: 'rgba(74, 222, 128, 0.05)',
  dim: 'transparent',
};

interface Props {
  lines: ConsoleLine[];
  height?: number;
  accent?: string;
  title?: string;
  status?: 'idle' | 'streaming' | 'done' | 'error';
}

export function ConsoleOutput({
  lines,
  height = 320,
  accent = '#8b5cf6',
  title = 'Live console',
  status = 'idle',
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines.length]);

  return (
    <div
      className="overflow-hidden rounded-xl border"
      style={{
        backgroundColor: 'var(--mars-color-console-bg)',
        borderColor: 'var(--mars-color-border)',
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.04), 0 8px 24px -8px ${accent}33`,
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between border-b px-3 py-2"
        style={{
          borderColor: 'var(--mars-color-border)',
          background: `linear-gradient(180deg, ${accent}14, transparent)`,
        }}
      >
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: '#ef4444' }} />
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: '#f59e0b' }} />
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: '#22c55e' }} />
          </span>
          <Terminal className="h-3.5 w-3.5" style={{ color: accent }} />
          <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-secondary)' }}>
            {title}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {status === 'streaming' && (
            <span className="flex items-center gap-1 text-[10px] font-semibold" style={{ color: accent }}>
              <Activity className="h-3 w-3 animate-pulse" />
              streaming
            </span>
          )}
          <span className="font-mono text-[10px] tabular-nums" style={{ color: 'var(--mars-color-text-disabled)' }}>
            {lines.length} line{lines.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {/* Body */}
      <div
        ref={ref}
        className="console-scrollbar overflow-auto px-3 py-2 font-mono text-[12px] leading-[1.55]"
        style={{ height, color: 'var(--mars-color-console-text)' }}
      >
        {lines.length === 0 ? (
          <div className="flex h-full items-center justify-center" style={{ color: 'var(--mars-color-text-disabled)' }}>
            <span className="inline-flex items-center gap-2 text-xs">
              <span className="inline-block h-2 w-2 animate-ping rounded-full" style={{ backgroundColor: accent }} />
              Waiting for output…
            </span>
          </div>
        ) : (
          lines.map((line, idx) => {
            const kind = classify(line.text);
            return (
              <div
                key={idx}
                className="flex gap-2 whitespace-pre-wrap rounded px-1 py-px"
                style={{ backgroundColor: LINE_BG[kind], color: LINE_COLOR[kind] }}
              >
                <span className="select-none tabular-nums" style={{ color: 'var(--mars-color-text-disabled)', minWidth: '2.25rem' }}>
                  {String(idx + 1).padStart(4, ' ')}
                </span>
                <span className="flex-1">{line.text}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
