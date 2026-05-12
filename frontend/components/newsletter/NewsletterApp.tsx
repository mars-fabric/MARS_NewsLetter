'use client';

import { AlertCircle, ArrowLeft } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import Stepper, { StepperStep } from '@/components/core/Stepper';
import { MarsLogo } from '@/components/layout/MarsLogo';
import { useNewsletterTask } from '@/hooks/useNewsletterTask';
import {
  CmbAgentMode,
  NewsletterCreateRequest,
  STAGE_ACCENT,
  STAGE_NAMES,
  StageInfo,
  StageIterationLimits,
  StageModelOverrides,
  StageModeConfig,
} from '@/types/newsletter';

import { SetupPanel } from './SetupPanel';
import { StageCard } from './StageCard';

interface NewsletterAppProps {
  resumeTaskId?: string | null;
  onBack?: () => void;
  onTaskCreated?: (taskId: string) => void;
}

const STAGE_NUMBERS = [1, 2, 3, 4, 5] as const;

function stageStatusToStep(stage: StageInfo | undefined, isActive: boolean): StepperStep['status'] {
  if (!stage) return 'pending';
  if (stage.status === 'completed') return 'completed';
  if (stage.status === 'failed') return 'failed';
  if (stage.status === 'running') return 'active';
  return isActive ? 'active' : 'pending';
}

export function NewsletterApp({ resumeTaskId = null, onBack, onTaskCreated }: NewsletterAppProps = {}) {
  const t = useNewsletterTask();
  const [activeStage, setActiveStage] = useState<number>(1);

  // Local clone of mode_config so the per-stage settings drawer can mutate it
  // without re-creating the task. The clone is initialised from the task's
  // setup once it's loaded; per-stage executions forward the relevant subset
  // as ``config_overrides``.
  const [liveModeConfig, setLiveModeConfig] = useState<StageModeConfig | null>(null);

  // Resume an existing task if a task_id was provided.
  useEffect(() => {
    if (resumeTaskId && t.taskId !== resumeTaskId) {
      void t.resume(resumeTaskId);
    }
  }, [resumeTaskId, t.taskId, t]);

  // When the task is created/loaded, jump to the first non-completed stage and
  // hydrate the mode-config clone.
  useEffect(() => {
    if (!t.task) return;
    if (!liveModeConfig && t.task.setup?.mode_config) {
      setLiveModeConfig(t.task.setup.mode_config);
    }
    const next = t.task.stages.find((s) => s.status !== 'completed');
    if (next) {
      setActiveStage(next.stage_number);
    } else {
      setActiveStage(t.task.stages[t.task.stages.length - 1]?.stage_number ?? 5);
    }
  }, [t.task, liveModeConfig]);

  // Auto-fetch content for any completed stage we haven't pulled yet (so when
  // the user clicks a stage in the stepper its rendered output is already there).
  useEffect(() => {
    if (!t.taskId || !t.task) return;
    for (const s of t.task.stages) {
      if (s.status === 'completed' && !t.stageContent[s.stage_number]) {
        void t.fetchStageContent(t.taskId, s.stage_number);
      }
    }
  }, [t.task?.stages, t.taskId, t.stageContent, t]);

  const handleCreate = async (req: NewsletterCreateRequest) => {
    const id = await t.create(req);
    if (id && onTaskCreated) onTaskCreated(id);
    setLiveModeConfig(req.mode_config);
    return id;
  };

  const stepperSteps: StepperStep[] = useMemo(() => {
    const stages = t.task?.stages ?? [];
    // The "current" stage to navigate to: the running one if any, otherwise the
    // first non-completed (pending) stage. Marking it as `active` here is what
    // makes it clickable in the stepper from anywhere — without this, a pending
    // stage stays gray / non-clickable so the user can't get back to it after
    // navigating away to a completed earlier stage.
    const currentNum =
      (stages.find((s) => s.status === 'running')?.stage_number)
      ?? (stages.find((s) => s.status !== 'completed')?.stage_number)
      ?? null;

    return STAGE_NUMBERS.map((n) => {
      const stage = stages.find((s) => s.stage_number === n);
      const status: StepperStep['status'] =
        n === 1 && t.taskId
          ? 'completed'
          : stageStatusToStep(stage, n === activeStage || n === currentNum);
      return { id: String(n), label: STAGE_NAMES[n], status };
    });
  }, [t.task, t.taskId, activeStage]);

  const activeStageInfo = t.task?.stages.find((s) => s.stage_number === activeStage) || null;

  // Build per-stage config_overrides from the live mode-config clone — the
  // backend accepts a flat dict, so we pre-merge model overrides + iteration
  // limits + (planning_and_control mode) into a single payload.
  function buildOverridesForStage(stageNum: number): {
    mode_override: CmbAgentMode | undefined;
    config_overrides: Record<string, unknown>;
  } {
    const cfg = liveModeConfig;
    const stageNumKey = stageNum as 2 | 3 | 4 | 5;
    if (!cfg || stageNum < 2) return { mode_override: undefined, config_overrides: {} };

    const models = (cfg[`stage_${stageNumKey}_models` as const] ?? {}) as StageModelOverrides;
    const limits = (cfg[`stage_${stageNumKey}_limits` as const] ?? {}) as StageIterationLimits;
    const mode = cfg[`stage_${stageNumKey}_mode` as const];

    const config_overrides: Record<string, unknown> = { ...models, ...limits };
    return { mode_override: mode, config_overrides };
  }

  function executeStage(stageNum: number) {
    if (!t.taskId) return;
    const { mode_override, config_overrides } = buildOverridesForStage(stageNum);
    void t.executeStage(t.taskId, stageNum, { mode_override, config_overrides });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      {/* Hero card */}
      <div
        className="relative overflow-hidden rounded-2xl border p-5"
        style={{
          background:
            'linear-gradient(135deg, rgba(139,92,246,0.12), rgba(99,102,241,0.06) 50%, rgba(15,23,42,0.5))',
          borderColor: 'rgba(139, 92, 246, 0.25)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          boxShadow: '0 12px 36px -12px rgba(99,102,241,0.35), inset 0 1px 0 rgba(255,255,255,0.04)',
        }}
      >
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.6), transparent)' }}
        />
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <MarsLogo size={48} />
            <div className="leading-tight">
              <h1
                className="text-2xl font-extrabold tracking-tight"
                style={{
                  background: 'linear-gradient(135deg, #ffffff 0%, #c7d2fe 50%, #a78bfa 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  backgroundClip: 'text',
                  letterSpacing: '-0.02em',
                }}
              >
                MARS · NewsLetter
              </h1>
              <p className="mt-1 max-w-xl text-[11.5px] leading-relaxed" style={{ color: 'var(--mars-color-text-secondary)' }}>
                Production-grade industry newsletter · 5 stages · top-N companies · ≥30 sources · authenticity score · cmbagent one_shot mode.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {typeof t.task?.total_cost_usd === 'number' && t.task.total_cost_usd > 0 && (
              <div
                className="rounded-lg px-3 py-1.5 font-mono text-xs tabular-nums"
                style={{
                  backgroundColor: 'var(--mars-color-surface-raised)',
                  color: 'var(--mars-color-text-secondary)',
                  border: '1px solid var(--mars-color-border)',
                }}
                title="Total cost so far"
              >
                <span style={{ color: 'var(--mars-color-text-tertiary)' }}>$</span>
                {t.task.total_cost_usd.toFixed(4)}
              </div>
            )}
            {onBack && (
              <button
                onClick={onBack}
                className="flex flex-shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all hover:-translate-x-0.5"
                style={{
                  border: '1px solid var(--mars-color-border)',
                  background: 'var(--mars-color-surface-overlay)',
                  color: 'var(--mars-color-text-secondary)',
                  backdropFilter: 'blur(6px)',
                  WebkitBackdropFilter: 'blur(6px)',
                }}
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Back to sessions
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stepper — replaces the old top tab bar. Each step is one stage. */}
      <div
        className="rounded-2xl border px-6 py-5"
        style={{
          background: 'linear-gradient(180deg, var(--mars-color-surface-raised), var(--mars-color-surface))',
          borderColor: 'var(--mars-color-border)',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 16px -8px rgba(0,0,0,0.20)',
        }}
      >
        <Stepper
          steps={stepperSteps}
          orientation="horizontal"
          size="sm"
          onStepClick={(idx) => {
            const num = STAGE_NUMBERS[idx];
            if (!num) return;
            if (num === 1) {
              setActiveStage(1);
              return;
            }
            // Only let the user jump to a stage whose prerequisites are completed.
            if (!t.task) return;
            const prior = t.task.stages
              .filter((s) => s.stage_number < num)
              .every((s) => s.status === 'completed');
            if (prior) setActiveStage(num);
          }}
        />
      </div>

      {/* Error banner */}
      {t.error && (
        <Card
          style={{
            borderColor: 'rgba(239, 68, 68, 0.4)',
            background: 'linear-gradient(135deg, rgba(239,68,68,0.10), rgba(239,68,68,0.02))',
          }}
        >
          <div className="flex items-start gap-2.5">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" style={{ color: 'var(--mars-color-danger)' }} />
            <div>
              <CardTitle className="text-red-300">Error</CardTitle>
              <CardSubtitle>{t.error}</CardSubtitle>
            </div>
          </div>
        </Card>
      )}

      {/* Active stage panel */}
      {activeStage === 1 ? (
        t.taskId ? (
          <SetupSummaryCard task={t.task} onContinue={() => setActiveStage(2)} />
        ) : (
          <SetupPanel busy={t.loading} onCreate={handleCreate} />
        )
      ) : (
        liveModeConfig && t.task && t.taskId && activeStageInfo && (
          <StageCard
            taskId={t.taskId}
            stage={activeStageInfo}
            stageContent={t.stageContent[activeStage] ?? null}
            consoleLines={t.console}
            modeConfig={liveModeConfig}
            onModeConfigChange={setLiveModeConfig}
            onExecute={() => executeStage(activeStage)}
            onUpdateContent={(content) => t.updateStageContent(t.taskId as string, activeStage, content)}
            onRegeneratePdf={activeStage === 5 ? () => t.regeneratePdf(t.taskId as string) : undefined}
            workDir={t.task.work_dir ?? ''}
            busy={t.loading}
          />
        )
      )}
    </div>
  );
}

function SetupSummaryCard({ task, onContinue }: { task: ReturnType<typeof useNewsletterTask>['task']; onContinue: () => void }) {
  const accent = STAGE_ACCENT[1];
  if (!task) return null;
  const setup = task.setup;
  return (
    <Card accent={accent} glow style={{ borderColor: `${accent}33` }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Setup complete</CardTitle>
          <CardSubtitle>{task.title?.trim() || 'New newsletter'} · ready to collect sources</CardSubtitle>
        </div>
        <button
          onClick={onContinue}
          className="rounded-lg px-4 py-2 text-sm font-semibold text-white transition-all hover:translate-x-0.5"
          style={{
            background: `linear-gradient(135deg, ${accent}, ${accent}cc)`,
            boxShadow: `0 4px 16px ${accent}66`,
          }}
        >
          Continue to Stage 2 →
        </button>
      </div>
      {setup && (
        <div className="mt-4 grid gap-3 text-xs md:grid-cols-2" style={{ color: 'var(--mars-color-text-secondary)' }}>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Coverage</div>
            <div>{setup.date_from} → {setup.date_to}</div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Audience</div>
            <div>{setup.audience || '(unspecified)'}</div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Industries</div>
            <div>{setup.industries.map((i) => i.industry).join(', ')}</div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Source mode</div>
            <div>{setup.source_mode} · {setup.user_urls.length} user URL(s)</div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Stage 2 targets</div>
            <div>Top {setup.mode_config.stage_2_top_companies_count} companies · ≥{setup.mode_config.stage_2_min_sources} sources</div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>Default mode</div>
            <div>{setup.mode_config.stage_3_mode}</div>
          </div>
        </div>
      )}
    </Card>
  );
}
