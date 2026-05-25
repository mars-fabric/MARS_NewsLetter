'use client';

import { Activity, Cog, Filter, Network, Terminal } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { ConsoleLine } from '@/hooks/useNewsletterTask';

type LineKind = 'info' | 'warn' | 'err' | 'ok' | 'dim' | 'plan' | 'control';

function classify(text: string): LineKind {
  const t = text.toLowerCase();
  if (/(error|traceback|failed|exception|fatal)/.test(t)) return 'err';
  if (/(warn|warning|⚠)/.test(t)) return 'warn';
  if (/(success|✓|completed|done|ok\b|finished)/.test(t)) return 'ok';
  if (/^(===|---|>>>|\s*$)/.test(text)) return 'dim';
  if (/(\bplanner\b|planning phase|plan_recorder|plan_reviewer|plan revision|plan_reviewer_response)/.test(t)) return 'plan';
  if (/(\bengineer\b|control phase|executor|step \d+ (?:of|succeeded|failed|skipped)|attempt \d+ of \d+)/.test(t)) return 'control';
  return 'info';
}

const LINE_COLOR: Record<LineKind, string> = {
  info: 'var(--mars-color-text)',
  warn: '#fbbf24',
  err: '#f87171',
  ok: '#4ade80',
  dim: 'var(--mars-color-text-tertiary)',
  plan: '#a78bfa',
  control: '#60a5fa',
};

const LINE_BG: Record<LineKind, string> = {
  info: 'transparent',
  warn: 'rgba(251, 191, 36, 0.06)',
  err: 'rgba(248, 113, 113, 0.08)',
  ok: 'rgba(74, 222, 128, 0.05)',
  dim: 'transparent',
  plan: 'rgba(167, 139, 250, 0.06)',
  control: 'rgba(96, 165, 250, 0.06)',
};

// Patterns the "Planning & Control" filter shows. Anything cmbagent's
// planner / engineer / researcher loop prints during a planning_and_control
// run. Kept loose so future agent name tweaks don't silently break the filter.
const PC_FILTER_RE =
  /(\bplanner\b|planning phase|control phase|\bengineer\b|\bresearcher\b|plan_recorder|plan_reviewer|step \d+|attempt \d+ of \d+|cmbagent|context_carry|executor)/i;

type Tab = 'all' | 'pc';

interface Props {
  lines: ConsoleLine[];
  height?: number;
  accent?: string;
  title?: string;
  status?: 'idle' | 'streaming' | 'done' | 'error';
  /** Whether to render the Planning & Control filter tab. Pass false on
   *  stages where the agent loop has nothing to surface (Stage 1 setup). */
  showPlanningControl?: boolean;
}

export function ConsoleOutput({
  lines,
  height = 320,
  accent = '#8b5cf6',
  title = 'Live console',
  status = 'idle',
  showPlanningControl = true,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<Tab>('all');

  const visibleLines = useMemo(() => {
    if (tab === 'all') return lines;
    return lines.filter((l) => PC_FILTER_RE.test(l.text));
  }, [lines, tab]);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [visibleLines.length]);

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
            {visibleLines.length}{tab === 'pc' ? `/${lines.length}` : ''} line{visibleLines.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {/* Tab bar — only render when P&C filter is enabled (most stages). */}
      {showPlanningControl && (
        <div
          className="flex items-center gap-1 border-b px-2 py-1.5"
          style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-sunken)' }}
        >
          <ConsoleTab
            active={tab === 'all'}
            onClick={() => setTab('all')}
            icon={<Filter className="h-3 w-3" />}
            label="All output"
            count={lines.length}
            accent={accent}
          />
          <ConsoleTab
            active={tab === 'pc'}
            onClick={() => setTab('pc')}
            icon={<Network className="h-3 w-3" />}
            label="Planning & Control"
            count={lines.filter((l) => PC_FILTER_RE.test(l.text)).length}
            accent="#a78bfa"
          />
          {tab === 'pc' && (
            <span
              className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
              style={{ background: 'rgba(167, 139, 250, 0.10)', color: '#c4b5fd' }}
              title="Showing only planner / researcher / engineer / step events from cmbagent's planning_and_control workflow."
            >
              <Cog className="h-3 w-3" />
              filter: planner · researcher · engineer · step events
            </span>
          )}
        </div>
      )}

      {/* Body */}
      <div
        ref={ref}
        className="console-scrollbar overflow-auto px-3 py-2 font-mono text-[12px] leading-[1.55]"
        style={{ height, color: 'var(--mars-color-console-text)' }}
      >
        {visibleLines.length === 0 ? (
          <div className="flex h-full items-center justify-center" style={{ color: 'var(--mars-color-text-disabled)' }}>
            <span className="inline-flex items-center gap-2 text-xs">
              <span className="inline-block h-2 w-2 animate-ping rounded-full" style={{ backgroundColor: accent }} />
              {tab === 'pc' && lines.length > 0
                ? 'No planning/control events yet — this stage may be running in one_shot mode.'
                : 'Waiting for output…'}
            </span>
          </div>
        ) : (
          visibleLines.map((line, idx) => {
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

function ConsoleTab({
  active,
  onClick,
  icon,
  label,
  count,
  accent,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
  accent: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-semibold transition-all"
      style={{
        background: active ? `${accent}1f` : 'transparent',
        color: active ? accent : 'var(--mars-color-text-secondary)',
        border: `1px solid ${active ? `${accent}55` : 'transparent'}`,
      }}
    >
      {icon}
      {label}
      <span
        className="ml-1 inline-block rounded px-1 font-mono text-[10px] tabular-nums"
        style={{
          background: active ? `${accent}33` : 'var(--mars-color-surface-overlay)',
          color: active ? accent : 'var(--mars-color-text-tertiary)',
        }}
      >
        {count}
      </span>
    </button>
  );
}
