'use client';

import { formatDistanceToNow } from 'date-fns';
import { CheckCircle2, ChevronRight, Clock, FileText, Play, Search, Trash2, XCircle } from 'lucide-react';
import React, { useMemo, useState } from 'react';

import { parseBackendDate } from '@/lib/dateUtils';
import { STAGE_NAMES } from '@/types/newsletter';

export interface SessionItem {
  task_id: string;
  title: string | null;
  status: string;
  created_at: string | null;
  current_stage: number | null;
  progress_percent: number;
}

const STAGE_COUNT = 5;
const DONE_COLOR = '#22c55e';

function StageBeads({
  current,
  status,
  color,
  progress,
}: {
  current: number | null;
  status: string;
  color: string;
  progress: number;
}) {
  const isRunning = status === 'executing' || status === 'running' || status === 'planning' || status === 'draft';
  const isFailed = status === 'failed';
  const isComplete = status === 'completed' || progress >= 100;

  const stageState = (n: number): 'done' | 'active' | 'pending' | 'failed' => {
    if (isComplete) return 'done';
    if (isFailed) {
      if (current && n === current) return 'failed';
      if (current && n < current) return 'done';
      return 'pending';
    }
    if (current && n < current) return 'done';
    if (current && n === current) return isRunning ? 'active' : 'done';
    return 'pending';
  };

  const colorFor = (s: 'done' | 'active' | 'pending' | 'failed') =>
    s === 'done' ? DONE_COLOR
      : s === 'active' ? color
        : s === 'failed' ? 'var(--mars-color-danger)'
          : 'var(--mars-color-surface-overlay)';

  const computedPct = (() => {
    if (isComplete) return 100;
    const stagePct = 100 / STAGE_COUNT;
    if (isFailed && current) return Math.min(100, ((current - 1) / STAGE_COUNT) * 100);
    if (!current) return 0;
    const base = ((current - 1) / STAGE_COUNT) * 100;
    const active = isRunning ? Math.min(progress / STAGE_COUNT, stagePct) : stagePct;
    return Math.min(100, base + active);
  })();

  const stages = Array.from({ length: STAGE_COUNT }, (_, i) => i + 1);

  return (
    <div className="flex items-center gap-2 mt-2" aria-label="Pipeline stages">
      <div className="flex items-center flex-1 min-w-0">
        {stages.map((n) => {
          const state = stageState(n);
          const nextState = n < STAGE_COUNT ? stageState(n + 1) : null;
          const dotColor = colorFor(state);
          const isLast = n === STAGE_COUNT;

          return (
            <React.Fragment key={n}>
              <span className="relative flex-shrink-0">
                {state === 'active' && (
                  <span
                    aria-hidden
                    className="absolute inset-0 rounded-full animate-ping"
                    style={{ backgroundColor: dotColor, opacity: 0.55 }}
                  />
                )}
                <span
                  className="relative block w-2 h-2 rounded-full transition-all duration-300"
                  style={{
                    backgroundColor: dotColor,
                    boxShadow:
                      state === 'done'
                        ? `0 0 0 1.5px ${DONE_COLOR}55`
                        : state === 'active'
                          ? `0 0 0 2px ${color}55, 0 0 8px ${color}aa`
                          : state === 'failed'
                            ? '0 0 0 1.5px var(--mars-color-danger)55'
                            : 'inset 0 0 0 1px var(--mars-color-border)',
                  }}
                />
              </span>

              {!isLast && (
                <span
                  className="flex-1 mx-1 h-[2px] rounded-full"
                  style={{
                    background: `linear-gradient(90deg, ${dotColor}, ${colorFor(nextState!)})`,
                    opacity: state === 'pending' && nextState === 'pending' ? 0.5 : 1,
                  }}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>

      <span
        className="text-[9px] flex-shrink-0 tabular-nums font-bold"
        style={{
          color: isComplete ? DONE_COLOR : isFailed ? 'var(--mars-color-danger)' : color,
        }}
      >
        {Math.round(computedPct)}%
      </span>
    </div>
  );
}

function getStatusConfig(status: string, progress: number) {
  if (status === 'executing' || status === 'running') {
    return {
      icon: Play,
      label: 'Running',
      color: 'var(--mars-color-warning)',
      bgColor: 'rgba(234, 179, 8, 0.1)',
      borderColor: 'rgba(234, 179, 8, 0.3)',
      pulse: true,
    };
  }
  if (status === 'completed' || progress >= 100) {
    return {
      icon: CheckCircle2,
      label: 'Completed',
      color: 'var(--mars-color-success)',
      bgColor: 'rgba(34, 197, 94, 0.1)',
      borderColor: 'rgba(34, 197, 94, 0.3)',
      pulse: false,
    };
  }
  if (status === 'failed') {
    return {
      icon: XCircle,
      label: 'Failed',
      color: 'var(--mars-color-danger)',
      bgColor: 'rgba(239, 68, 68, 0.1)',
      borderColor: 'rgba(239, 68, 68, 0.3)',
      pulse: false,
    };
  }
  return {
    icon: Clock,
    label: 'In Progress',
    color: 'var(--mars-color-primary)',
    bgColor: 'rgba(59, 130, 246, 0.1)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
    pulse: false,
  };
}

interface SessionSidebarProps {
  sessions: SessionItem[];
  activeSessionId: string | null;
  onSelectSession: (taskId: string) => void;
  onDeleteSession: (taskId: string) => void;
  collapsed?: boolean;
  width?: number;
}

export default function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
  collapsed = false,
  width = 280,
}: SessionSidebarProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<'all' | 'running' | 'completed' | 'failed'>('all');

  const filteredSessions = useMemo(() => {
    return sessions.filter((s) => {
      const matchesSearch = !searchQuery
        || (s.title || '').toLowerCase().includes(searchQuery.toLowerCase())
        || s.task_id.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesFilter =
        filterStatus === 'all'
        || (filterStatus === 'running' && (s.status === 'executing' || s.status === 'running' || s.status === 'draft' || s.status === 'planning'))
        || (filterStatus === 'completed' && (s.status === 'completed' || s.progress_percent >= 100))
        || (filterStatus === 'failed' && s.status === 'failed');
      return matchesSearch && matchesFilter;
    });
  }, [sessions, searchQuery, filterStatus]);

  const statusCounts = useMemo(() => {
    const running = sessions.filter((s) => s.status === 'executing' || s.status === 'running' || s.status === 'draft' || s.status === 'planning').length;
    const completed = sessions.filter((s) => s.status === 'completed' || s.progress_percent >= 100).length;
    const failed = sessions.filter((s) => s.status === 'failed').length;
    return { all: sessions.length, running, completed, failed };
  }, [sessions]);

  const isWide = width >= 360;

  if (collapsed) return null;

  return (
    <div
      className="relative h-full flex flex-col border-l"
      style={{
        width: '100%',
        minWidth: '0',
        backgroundColor: 'var(--mars-color-surface)',
        borderColor: 'var(--mars-color-border)',
      }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-px left-0 right-0 h-px"
        style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.4), transparent)' }}
      />

      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b" style={{ borderColor: 'var(--mars-color-border)' }}>
        <div className="flex items-center justify-between mb-2.5">
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Sessions
          </h3>
          <span
            className="px-1.5 py-0.5 rounded-full text-[9px] font-bold tabular-nums"
            style={{ backgroundColor: 'var(--mars-color-primary-subtle)', color: 'var(--mars-color-primary)' }}
          >
            {sessions.length}
          </span>
        </div>

        {/* Search */}
        <div
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs transition-all duration-200 focus-within:ring-2"
          style={{
            backgroundColor: 'var(--mars-color-surface-sunken)',
            border: '1px solid var(--mars-color-border)',
            boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.15)',
          }}
        >
          <Search className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--mars-color-text-tertiary)' }} />
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-transparent outline-none text-xs"
            style={{ color: 'var(--mars-color-text)' }}
          />
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-1 mt-2.5">
          {(['all', 'running', 'completed', 'failed'] as const).map((filter) => {
            const active = filterStatus === filter;
            return (
              <button
                key={filter}
                onClick={() => setFilterStatus(filter)}
                className="flex-1 px-2 py-1 rounded-md text-[10px] font-semibold capitalize transition-all duration-200"
                style={{
                  background: active
                    ? 'linear-gradient(135deg, rgba(139,92,246,0.20), rgba(99,102,241,0.20))'
                    : 'transparent',
                  color: active ? 'var(--mars-color-primary)' : 'var(--mars-color-text-tertiary)',
                  border: active ? '1px solid rgba(139,92,246,0.40)' : '1px solid transparent',
                  boxShadow: active ? '0 0 12px rgba(139,92,246,0.20)' : 'none',
                }}
              >
                {filter} {statusCounts[filter] > 0 && <span className="opacity-75">({statusCounts[filter]})</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto py-1.5">
        {filteredSessions.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <FileText className="w-8 h-8 mx-auto mb-2" style={{ color: 'var(--mars-color-text-disabled)' }} />
            <p className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
              {searchQuery ? 'No matching sessions' : 'No sessions yet'}
            </p>
          </div>
        ) : (
          filteredSessions.map((session) => {
            const statusCfg = getStatusConfig(session.status, session.progress_percent);
            const StatusIcon = statusCfg.icon;
            const isActive = session.task_id === activeSessionId;
            const isRunning = statusCfg.pulse;

            return (
              <div
                key={session.task_id}
                role="button"
                tabIndex={0}
                onClick={() => onSelectSession(session.task_id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelectSession(session.task_id);
                  }
                }}
                className="relative w-full text-left px-3 py-2.5 mx-1.5 mb-1 rounded-lg transition-all duration-200 group cursor-pointer hover:translate-x-0.5"
                style={{
                  width: 'calc(100% - 12px)',
                  background: isActive
                    ? 'linear-gradient(135deg, rgba(139,92,246,0.18), rgba(99,102,241,0.10))'
                    : 'transparent',
                  border: isActive ? '1px solid rgba(139,92,246,0.45)' : '1px solid transparent',
                  boxShadow: isActive
                    ? '0 4px 16px -4px rgba(139,92,246,0.30), inset 0 1px 0 rgba(255,255,255,0.05)'
                    : 'none',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'var(--mars-color-bg-hover)';
                    e.currentTarget.style.border = '1px solid var(--mars-color-border)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.border = '1px solid transparent';
                  }
                }}
              >
                {isActive && (
                  <div
                    aria-hidden
                    className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full"
                    style={{
                      background: 'linear-gradient(180deg, #8b5cf6, #6366f1)',
                      boxShadow: '0 0 8px rgba(139,92,246,0.7)',
                    }}
                  />
                )}

                <div className="flex items-start gap-2.5">
                  <div
                    className={`relative flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5 ${isRunning ? 'animate-pulse' : ''}`}
                    style={{
                      backgroundColor: statusCfg.bgColor,
                      border: `1px solid ${statusCfg.borderColor}`,
                      boxShadow: isRunning ? `0 0 12px ${statusCfg.bgColor}` : 'none',
                    }}
                  >
                    <StatusIcon className="w-3.5 h-3.5" style={{ color: statusCfg.color }} />
                  </div>

                  <div className="flex-1 min-w-0">
                    <p
                      className={`${isWide ? 'text-sm' : 'text-xs'} font-semibold truncate leading-tight`}
                      style={{ color: isActive ? 'var(--mars-color-primary)' : 'var(--mars-color-text)' }}
                    >
                      {session.title?.trim() || 'New newsletter'}
                    </p>

                    <div className="flex items-center gap-1.5 mt-1">
                      <span
                        className="text-[10px] font-semibold px-1.5 py-0.5 rounded-md"
                        style={{
                          backgroundColor: statusCfg.bgColor,
                          color: statusCfg.color,
                          border: `1px solid ${statusCfg.borderColor}`,
                        }}
                      >
                        {statusCfg.label}
                      </span>
                      <span className="text-[10px] truncate flex-1" style={{ color: 'var(--mars-color-text-secondary)' }}>
                        {session.current_stage
                          ? `${STAGE_NAMES[session.current_stage] || ''}`
                          : (statusCfg.label === 'Completed' ? 'All stages done' : 'Setup')}
                      </span>
                      {isRunning && (
                        <span className="inline-flex items-center gap-0.5 flex-shrink-0" aria-label="thinking">
                          <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: statusCfg.color, animationDelay: '0ms' }} />
                          <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: statusCfg.color, animationDelay: '120ms' }} />
                          <span className="w-1 h-1 rounded-full animate-bounce" style={{ backgroundColor: statusCfg.color, animationDelay: '240ms' }} />
                        </span>
                      )}
                    </div>

                    <StageBeads
                      current={session.current_stage}
                      status={session.status}
                      color={statusCfg.color}
                      progress={session.progress_percent}
                    />

                    {(() => {
                      const d = parseBackendDate(session.created_at);
                      return (
                        <div className="flex items-center justify-between mt-1.5 gap-2">
                          {d ? (
                            <p className="text-[9px]" style={{ color: 'var(--mars-color-text-disabled)' }}>
                              {formatDistanceToNow(d, { addSuffix: true })}
                            </p>
                          ) : <span />}
                          {isWide && (
                            <p
                              className="text-[9px] font-mono truncate"
                              style={{ color: 'var(--mars-color-text-disabled)' }}
                              title={session.task_id}
                            >
                              {session.task_id.slice(0, 8)}
                            </p>
                          )}
                        </div>
                      );
                    })()}
                  </div>

                  <div className="flex-shrink-0 flex flex-col items-end gap-1">
                    <ChevronRight
                      className="w-3.5 h-3.5 transition-transform duration-200 group-hover:translate-x-0.5"
                      style={{
                        color: isActive ? 'var(--mars-color-primary)' : 'var(--mars-color-text-tertiary)',
                        opacity: isActive ? 1 : 0.5,
                      }}
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(session.task_id);
                      }}
                      className="p-1 rounded transition-all duration-150 opacity-0 group-hover:opacity-100 hover:bg-[rgba(239,68,68,0.15)] hover:scale-110"
                      title="Delete session"
                    >
                      <Trash2 className="w-3 h-3" style={{ color: 'var(--mars-color-danger)' }} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-4 py-2.5 border-t text-center" style={{ borderColor: 'var(--mars-color-border)' }}>
        <p className="text-[10px]" style={{ color: 'var(--mars-color-text-disabled)' }}>
          {sessions.length} session{sessions.length !== 1 ? 's' : ''} total
        </p>
      </div>
    </div>
  );
}
