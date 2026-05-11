'use client';

import { CheckCircle2, Circle, Loader2, Play, RefreshCw, XCircle } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import Stepper, { StepperStep } from '@/components/core/Stepper';
import { ConsoleLine } from '@/hooks/useNewsletterTask';
import {
  CmbAgentMode,
  STAGE_ACCENT,
  STAGE_DESCRIPTIONS,
  STAGE_NAMES,
  StageInfo,
  TaskState,
} from '@/types/newsletter';

import { ConsoleOutput } from './ConsoleOutput';

function stageToStepStatus(s: StageInfo, isActive: boolean): StepperStep['status'] {
  if (s.status === 'completed') return 'completed';
  if (s.status === 'failed') return 'failed';
  if (s.status === 'running') return 'active';
  return isActive ? 'active' : 'pending';
}

interface Props {
  task: TaskState;
  consoleLines: ConsoleLine[];
  onExecute: (stageNum: number, overrides?: { mode_override?: CmbAgentMode }) => void;
  busy?: boolean;
}

export function ExecutionPanel({ task, consoleLines, onExecute, busy }: Props) {
  const [activeStage, setActiveStage] = useState<number>(() => task.current_stage ?? 2);
  const stage: StageInfo | undefined = task.stages.find((s) => s.stage_number === activeStage);
  const accent = STAGE_ACCENT[activeStage] ?? '#8b5cf6';
  const completedCount = task.stages.filter((s) => s.status === 'completed').length;

  function nextStageNum(): number | null {
    for (const s of task.stages) {
      if (s.status !== 'completed') return s.stage_number;
    }
    return null;
  }

  // Stepper view of the 5-stage pipeline. Statuses come from the backend; the
  // currently selected stage is treated as "active" only when it's running or
  // pending — already-completed stages keep their green check.
  const stepperSteps: StepperStep[] = task.stages
    .slice()
    .sort((a, b) => a.stage_number - b.stage_number)
    .map((s) => ({
      id: String(s.stage_number),
      label: STAGE_NAMES[s.stage_number] ?? `Stage ${s.stage_number}`,
      status: stageToStepStatus(s, s.stage_number === activeStage),
      description: s.mode ? `mode · ${s.mode}` : undefined,
    }));

  return (
    <div className="space-y-4">
      {/* Run header */}
      <Card accent="#8b5cf6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>
              {task.title || 'Untitled run'}
              <span
                className="ml-2 inline-block rounded px-1.5 py-0.5 align-middle font-mono text-[10px]"
                style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text-tertiary)' }}
              >
                STAGE {Math.max(1, completedCount)}/{task.stages.length}
              </span>
              {typeof task.total_cost_usd === 'number' && task.total_cost_usd > 0 && (
                <span
                  className="ml-2 inline-block rounded px-1.5 py-0.5 align-middle font-mono text-[10px]"
                  style={{
                    background: 'rgba(34,197,94,0.12)',
                    color: '#86efac',
                    border: '1px solid rgba(34,197,94,0.25)',
                  }}
                  title="Total spend across all stages of this run"
                >
                  ${task.total_cost_usd.toFixed(4)}
                </span>
              )}
            </CardTitle>
            <CardSubtitle>
              <span
                className="mr-1.5 rounded px-1.5 py-0.5 font-mono text-[10px]"
                style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text-tertiary)' }}
              >
                {task.task_id.slice(0, 8)}
              </span>
              MARS Newsletter pipeline
            </CardSubtitle>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold tabular-nums" style={{ color: 'var(--mars-color-text)' }}>
              {task.progress_percent}%
            </span>
            <div
              className="relative h-2 w-48 overflow-hidden rounded-full"
              style={{ backgroundColor: 'var(--mars-color-surface-overlay)' }}
            >
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${task.progress_percent}%`,
                  background: 'linear-gradient(90deg, #8b5cf6, #6366f1, #3b82f6)',
                  boxShadow: '0 0 12px rgba(139,92,246,0.5)',
                }}
              />
            </div>
          </div>
        </div>

        {/* Horizontal stepper — same shape as PaperPulse, click a step to jump */}
        <div className="mt-5 px-2">
          <Stepper
            steps={stepperSteps}
            orientation="horizontal"
            onStepClick={(idx) => {
              const step = stepperSteps[idx];
              if (step) setActiveStage(parseInt(step.id, 10));
            }}
          />
        </div>
      </Card>

      {/* Stage tiles */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
        {task.stages.map((s) => (
          <StageTile
            key={s.stage_number}
            stage={s}
            isActive={s.stage_number === activeStage}
            onClick={() => setActiveStage(s.stage_number)}
          />
        ))}
      </div>

      {/* Active stage detail */}
      {stage && (
        <Card accent={accent} glow style={{ borderColor: `${accent}33` }}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <div
                className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl text-base font-bold text-white"
                style={{
                  background: `linear-gradient(135deg, ${accent}, ${accent}aa)`,
                  boxShadow: `0 4px 16px ${accent}66`,
                }}
              >
                {stage.stage_number}
              </div>
              <div>
                <CardTitle>
                  {STAGE_NAMES[stage.stage_number]}
                </CardTitle>
                <CardSubtitle>{STAGE_DESCRIPTIONS[stage.stage_number]}</CardSubtitle>
                {stage.mode && (
                  <div
                    className="mt-1.5 inline-block rounded font-mono text-[10px] px-1.5 py-0.5"
                    style={{ background: 'var(--mars-color-surface-overlay)', color: accent }}
                  >
                    mode · {stage.mode}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {stage.stage_number > 1 && (
                <Button
                  variant={stage.status === 'completed' ? 'secondary' : 'primary'}
                  onClick={() => onExecute(stage.stage_number)}
                  disabled={busy || stage.status === 'running'}
                  loading={stage.status === 'running'}
                >
                  {stage.status === 'completed' ? (
                    <>
                      <RefreshCw size={14} /> Re-run
                    </>
                  ) : (
                    <>
                      <Play size={14} /> Run stage {stage.stage_number}
                    </>
                  )}
                </Button>
              )}
              {stage.stage_number === 1 && stage.status === 'completed' && nextStageNum() && (
                <Button onClick={() => setActiveStage(nextStageNum() as number)}>
                  Continue to stage {nextStageNum()} →
                </Button>
              )}
            </div>
          </div>

          {stage.error && (
            <div
              className="mt-3 rounded-lg border px-3 py-2 text-xs"
              style={{
                borderColor: 'rgba(239, 68, 68, 0.4)',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                color: '#fca5a5',
              }}
            >
              {stage.error}
            </div>
          )}

          <div className="mt-4">
            <ConsoleOutput
              lines={consoleLines.filter((l) => l.stage_num === stage.stage_number)}
              accent={accent}
              title={`Stage ${stage.stage_number} · ${STAGE_NAMES[stage.stage_number]}`}
              status={
                stage.status === 'running' ? 'streaming'
                  : stage.status === 'completed' ? 'done'
                    : stage.status === 'failed' ? 'error'
                      : 'idle'
              }
              height={360}
            />
          </div>
        </Card>
      )}
    </div>
  );
}

function StageTile({
  stage,
  isActive,
  onClick,
}: {
  stage: StageInfo;
  isActive: boolean;
  onClick: () => void;
}) {
  const accent = STAGE_ACCENT[stage.stage_number] ?? '#8b5cf6';
  const Icon =
    stage.status === 'completed' ? CheckCircle2
      : stage.status === 'failed' ? XCircle
        : stage.status === 'running' ? Loader2
          : Circle;
  const iconColor =
    stage.status === 'completed' ? 'var(--mars-color-success)'
      : stage.status === 'failed' ? 'var(--mars-color-danger)'
        : stage.status === 'running' ? accent
          : 'var(--mars-color-text-tertiary)';

  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative overflow-hidden rounded-xl border p-3 text-left transition-all duration-200 hover:-translate-y-0.5"
      style={{
        borderColor: isActive ? `${accent}80` : 'var(--mars-color-border)',
        background: isActive
          ? `linear-gradient(135deg, ${accent}1f, ${accent}08)`
          : 'var(--mars-color-surface-raised)',
        boxShadow: isActive
          ? `0 8px 24px -8px ${accent}80, inset 0 1px 0 rgba(255,255,255,0.05)`
          : '0 2px 8px rgba(0,0,0,0.15)',
      }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)`, opacity: isActive ? 1 : 0.3 }}
      />
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: accent }}>
          Stage {stage.stage_number}
        </div>
        <Icon
          className={`h-3.5 w-3.5 ${stage.status === 'running' ? 'animate-spin' : ''}`}
          style={{ color: iconColor }}
        />
      </div>
      <div
        className="mt-1.5 text-[13px] font-semibold leading-tight"
        style={{ color: isActive ? 'var(--mars-color-text)' : 'var(--mars-color-text-secondary)' }}
      >
        {STAGE_NAMES[stage.stage_number]}
      </div>
      {stage.mode && (
        <div className="mt-1 truncate font-mono text-[10px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
          {stage.mode}
        </div>
      )}
      {typeof stage.cost_usd === 'number' && stage.cost_usd > 0 && (
        <div
          className="mt-0.5 font-mono text-[10px] tabular-nums"
          style={{ color: '#86efac' }}
          title="Cost spent on this stage"
        >
          ${stage.cost_usd.toFixed(4)}
        </div>
      )}
      {stage.error && (
        <div className="mt-1 line-clamp-2 text-[10px]" style={{ color: '#fca5a5' }}>
          {stage.error}
        </div>
      )}
    </button>
  );
}
