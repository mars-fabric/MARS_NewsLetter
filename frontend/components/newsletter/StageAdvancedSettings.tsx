'use client';

import { ChevronDown, Plus, Settings2, X } from 'lucide-react';
import { useState } from 'react';

import { Label } from '@/components/core/Input';
import { useModelConfig, resolveStageDefault, type ModelOption } from '@/hooks/useModelConfig';
import {
  CmbAgentMode,
  STAGE_ACCENT,
  STAGE_LIMIT_DEFAULTS,
  STAGE_MODEL_DEFAULTS,
  StageIterationLimits,
  StageModelOverrides,
  StageModeConfig,
} from '@/types/newsletter';

interface Props {
  value: StageModeConfig;
  onChange: (next: StageModeConfig) => void;
  /** Restrict the visible stages — handy when this drawer is rendered next to a single stage card. */
  stages?: number[];
}

// planning_and_control is the PaperPulse / NewsPulse workflow: a planner
// builds a step-by-step blueprint, then a researcher/engineer pair executes
// each step with context carryover between steps. Slower than one_shot but
// yields more thorough Stage 2 (source collection) and Stage 3 (curation)
// output. Stage 4 always overrides to its custom section-by-section writer
// regardless of mode (see backend/task_framework/newsletter/stage4/).
const MODES: { value: CmbAgentMode; label: string; help: string }[] = [
  {
    value: 'one_shot',
    label: 'one_shot',
    help: 'Single researcher agent — fastest. Best for stable, well-scoped prompts.',
  },
  {
    value: 'planning_and_control',
    label: 'planning_and_control',
    help: 'Planner → researcher → engineer with cross-step context carryover. Slower but deeper coverage. Stages 2 & 3 benefit most.',
  },
];

type StageNum = 2 | 3 | 4 | 5;
type ModeKey = `stage_${StageNum}_mode`;
type ModelsKey = `stage_${StageNum}_models`;
type LimitsKey = `stage_${StageNum}_limits`;

const STAGE_META: { num: StageNum; label: string; modeKey: ModeKey; modelsKey: ModelsKey; limitsKey: LimitsKey }[] = [
  {
    num: 2,
    label: 'Stage 2 · Source Collection',
    modeKey: 'stage_2_mode',
    modelsKey: 'stage_2_models',
    limitsKey: 'stage_2_limits',
  },
  {
    num: 3,
    label: 'Stage 3 · Curation',
    modeKey: 'stage_3_mode',
    modelsKey: 'stage_3_models',
    limitsKey: 'stage_3_limits',
  },
  {
    num: 4,
    label: 'Stage 4 · Generation',
    modeKey: 'stage_4_mode',
    modelsKey: 'stage_4_models',
    limitsKey: 'stage_4_limits',
  },
  {
    num: 5,
    label: 'Stage 5 · Review & Publish',
    modeKey: 'stage_5_mode',
    modelsKey: 'stage_5_models',
    limitsKey: 'stage_5_limits',
  },
];

const MODEL_ROLES: { key: keyof StageModelOverrides; label: string; planningOnly: boolean; help: string }[] = [
  { key: 'model', label: 'Primary / Researcher', planningOnly: false, help: 'one_shot agent. In planning_and_control this maps to the executor (engineer_model).' },
  { key: 'researcher_model', label: 'Researcher', planningOnly: true, help: 'Researcher role in planning_and_control.' },
  { key: 'engineer_model', label: 'Engineer / Executor', planningOnly: true, help: 'Step executor.' },
  { key: 'web_surfer_model', label: 'Web Surfer (DDGS)', planningOnly: false, help: 'Drives DDGS / web tools when the stage searches the web.' },
  { key: 'planner_model', label: 'Planner', planningOnly: true, help: 'Drafts the multi-step plan.' },
  { key: 'plan_reviewer_model', label: 'Plan Reviewer', planningOnly: true, help: 'Critiques and tightens the plan.' },
  { key: 'formatter_model', label: 'Response Formatter', planningOnly: false, help: 'Formats the final response.' },
  { key: 'orchestration_model', label: 'Orchestration / Default LLM', planningOnly: true, help: 'Coordinates step transitions and acts as the fallback LLM.' },
];

const LIMIT_FIELDS: { key: keyof StageIterationLimits; label: string; planningOnly: boolean; min: number; max: number; help: string }[] = [
  { key: 'n_plan_reviews', label: 'n_plan_reviews', planningOnly: true, min: 0, max: 10, help: 'How many plan-review iterations to run.' },
  { key: 'max_plan_steps', label: 'max_plan_steps', planningOnly: true, min: 1, max: 20, help: 'Cap on the planner-emitted step count.' },
  { key: 'max_n_attempts', label: 'max_n_attempts', planningOnly: false, min: 1, max: 20, help: 'Per-step retry cap.' },
  { key: 'max_rounds_planning', label: 'max_rounds_planning', planningOnly: true, min: 1, max: 200, help: 'Round limit during the planning phase.' },
  { key: 'max_rounds_control', label: 'max_rounds_control', planningOnly: true, min: 1, max: 2000, help: 'Round limit during the control / execution phase.' },
  { key: 'max_rounds', label: 'max_rounds (one_shot)', planningOnly: false, min: 1, max: 200, help: 'one_shot total round cap.' },
];

export function StageAdvancedSettings({ value, onChange, stages }: Props) {
  const [open, setOpen] = useState(false);
  const { availableModels, customModels, addCustomModel, removeCustomModel, workflowDefaults } = useModelConfig();

  const visibleStages = STAGE_META.filter((s) => !stages || stages.includes(s.num));

  function setAllModes(mode: CmbAgentMode) {
    const patch: Partial<StageModeConfig> = {};
    visibleStages.forEach((s) => {
      patch[s.modeKey] = mode;
    });
    onChange({ ...value, ...patch });
  }

  function setStageMode(modeKey: ModeKey, mode: CmbAgentMode) {
    onChange({ ...value, [modeKey]: mode });
  }

  function setStageModel(modelsKey: ModelsKey, role: keyof StageModelOverrides, next: string) {
    const current = value[modelsKey] ?? {};
    const merged: StageModelOverrides = { ...current };
    if (next) {
      merged[role] = next;
    } else {
      delete merged[role];
    }
    onChange({ ...value, [modelsKey]: merged });
  }

  function setStageLimit(limitsKey: LimitsKey, key: keyof StageIterationLimits, next: number | null) {
    const current = value[limitsKey] ?? {};
    const merged: StageIterationLimits = { ...current };
    if (next === null || Number.isNaN(next as number)) {
      delete merged[key];
    } else {
      merged[key] = next as number;
    }
    onChange({ ...value, [limitsKey]: merged });
  }

  const resolveModelDefault = (stageNum: number, role: keyof StageModelOverrides): string =>
    resolveStageDefault(workflowDefaults, 'newsletter', stageNum, role as string, STAGE_MODEL_DEFAULTS[role]);

  return (
    <div
      className="overflow-hidden rounded-xl border"
      style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-raised)' }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold transition-colors"
        style={{ color: 'var(--mars-color-text)' }}
      >
        <span className="flex items-center gap-2">
          <Settings2 className="h-4 w-4" style={{ color: 'var(--mars-color-text-tertiary)' }} />
          {visibleStages.length === 1
            ? `${visibleStages[0].label} — agent / model / iteration knobs`
            : 'Per-stage agent mode, models & iteration knobs'}
        </span>
        <ChevronDown
          size={16}
          className={`transition-transform ${open ? 'rotate-180' : ''}`}
          style={{ color: 'var(--mars-color-text-tertiary)' }}
        />
      </button>

      {open && (
        <div
          className="space-y-5 p-4"
          style={{ borderTop: '1px solid var(--mars-color-border)', background: 'var(--mars-color-surface-sunken)' }}
        >
          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Choose the per-stage cmbagent mode + per-role model + iteration knobs.
            Empty model fields keep the cmbagent default. <code className="rounded px-1 font-mono text-[10px]" style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text)' }}>one_shot</code> runs a single researcher agent (fastest);{' '}
            <code className="rounded px-1 font-mono text-[10px]" style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text)' }}>planning_and_control</code> runs a planner → researcher → engineer pipeline with cross-step context carryover (slower but deeper coverage). Stage 4 always uses the section-by-section writer regardless of mode.
          </p>

          {visibleStages.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                Set all stages:
              </span>
              {MODES.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => setAllModes(m.value)}
                  className="mars-pill rounded-full px-3 py-1 font-mono text-[10px]"
                >
                  {m.label}
                </button>
              ))}
            </div>
          )}

          <CustomModelManager
            customModels={customModels}
            onAdd={addCustomModel}
            onRemove={removeCustomModel}
          />

          {visibleStages.map(({ num, label, modeKey, modelsKey, limitsKey }) => {
            const accent = STAGE_ACCENT[num];
            const currentMode = value[modeKey];
            const currentModels = value[modelsKey] ?? {};
            const currentLimits = value[limitsKey] ?? {};
            return (
              <div key={modeKey} className="space-y-3">
                <Label>
                  <span
                    className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: accent, boxShadow: `0 0 6px ${accent}` }}
                  />
                  {label}
                </Label>

                {/* Mode cards */}
                <div className="grid gap-2 md:grid-cols-2">
                  {MODES.map((m) => {
                    const active = currentMode === m.value;
                    return (
                      <label
                        key={m.value}
                        className="cursor-pointer rounded-lg border p-2.5 transition-all duration-150"
                        style={{
                          borderColor: active ? `${accent}80` : 'var(--mars-color-border)',
                          background: active
                            ? `linear-gradient(135deg, ${accent}1a, ${accent}06)`
                            : 'var(--mars-color-surface-raised)',
                          boxShadow: active ? `0 0 10px ${accent}33` : 'none',
                        }}
                      >
                        <input
                          type="radio"
                          className="sr-only"
                          name={modeKey}
                          value={m.value}
                          checked={active}
                          onChange={() => setStageMode(modeKey, m.value)}
                        />
                        <div className="font-mono text-[11px] font-semibold" style={{ color: active ? accent : 'var(--mars-color-text)' }}>
                          {m.label}
                        </div>
                        <div className="mt-1 text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                          {m.help}
                        </div>
                      </label>
                    );
                  })}
                </div>

                {/* Per-role model dropdowns */}
                <div className="rounded-lg border p-3" style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-raised)' }}>
                  <div className="mb-2 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                    Models
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    {MODEL_ROLES.map(({ key, label: roleLabel, planningOnly, help }) => {
                      const disabled = planningOnly && currentMode !== 'planning_and_control';
                      return (
                        <ModelSelect
                          key={key}
                          label={roleLabel}
                          defaultValue={resolveModelDefault(num, key)}
                          value={currentModels[key]}
                          models={availableModels}
                          disabled={disabled}
                          help={disabled ? `${help} (inactive in one_shot)` : help}
                          onChange={(v) => setStageModel(modelsKey, key, v)}
                        />
                      );
                    })}
                  </div>
                </div>

                {/* Iteration knobs */}
                <div className="rounded-lg border p-3" style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-raised)' }}>
                  <div className="mb-2 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                    Iteration limits (blank = cmbagent default)
                  </div>
                  <div className="grid gap-2 md:grid-cols-3">
                    {LIMIT_FIELDS.map((f) => {
                      const disabledForMode =
                        (f.planningOnly && currentMode !== 'planning_and_control') ||
                        (f.key === 'max_rounds' && currentMode === 'planning_and_control');
                      return (
                        <LimitInput
                          key={f.key}
                          label={f.label}
                          defaultValue={STAGE_LIMIT_DEFAULTS[f.key]}
                          value={currentLimits[f.key]}
                          min={f.min}
                          max={f.max}
                          disabled={disabledForMode}
                          help={disabledForMode ? `${f.help} (inactive in this mode)` : f.help}
                          onChange={(v) => setStageLimit(limitsKey, f.key, v)}
                        />
                      );
                    })}
                  </div>
                </div>

                {num === 2 && (
                  <div className="grid gap-2 rounded-lg border p-3 md:grid-cols-3" style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-raised)' }}>
                    <NumberField
                      label="Top-N companies (Stage 2-A)"
                      value={value.stage_2_top_companies_count}
                      min={0}
                      max={30}
                      help="Companies discovered before per-company news extraction. 0 disables the substep."
                      onChange={(v) => onChange({ ...value, stage_2_top_companies_count: v })}
                    />
                    <NumberField
                      label="Min sources"
                      value={value.stage_2_min_sources}
                      min={10}
                      max={200}
                      help="Researcher must collect at least this many unique sources industry-wide."
                      onChange={(v) => onChange({ ...value, stage_2_min_sources: v })}
                    />
                    <label className="flex items-start gap-2 rounded-lg p-2" style={{ border: '1px solid var(--mars-color-border)', background: 'var(--mars-color-surface)' }}>
                      <input
                        type="checkbox"
                        className="mt-0.5 h-3.5 w-3.5 cursor-pointer accent-violet-500"
                        checked={value.stage_2_enrich_with_llm}
                        onChange={(e) => onChange({ ...value, stage_2_enrich_with_llm: e.target.checked })}
                      />
                      <span className="text-[11px] leading-relaxed" style={{ color: 'var(--mars-color-text-secondary)' }}>
                        Enrich user-provided URLs with an LLM pass when source mode is user_links_only.
                      </span>
                    </label>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CustomModelManager({
  customModels,
  onAdd,
  onRemove,
}: {
  customModels: ModelOption[];
  onAdd: (value: string, label?: string) => void;
  onRemove: (value: string) => void;
}) {
  const [value, setValue] = useState('');
  const [label, setLabel] = useState('');
  const [open, setOpen] = useState(false);

  function commit() {
    const trimmed = value.trim();
    if (!trimmed) return;
    onAdd(trimmed, label.trim() || undefined);
    setValue('');
    setLabel('');
  }

  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--mars-color-border)', background: 'var(--mars-color-surface-raised)' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left text-[11px] font-semibold"
        style={{ color: 'var(--mars-color-text-secondary)' }}
      >
        <span className="flex items-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Add a custom model id (e.g. <code className="font-mono">gpt-5</code>)
        </span>
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} style={{ color: 'var(--mars-color-text-tertiary)' }} />
      </button>

      {open && (
        <div className="mt-2.5 space-y-2.5">
          <p className="text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Type the model identifier exactly as your LLM provider expects it. Custom entries appear at the top of every model dropdown below and are saved to your browser only.
          </p>
          <div className="grid gap-2 md:grid-cols-[2fr_1fr_auto]">
            <input
              type="text"
              placeholder="model id (e.g. gpt-5-2025-08-07)"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
              className="rounded border px-2 py-1.5 font-mono text-xs outline-none"
              style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
            />
            <input
              type="text"
              placeholder="display label (optional)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
              className="rounded border px-2 py-1.5 text-xs outline-none"
              style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
            />
            <button
              type="button"
              onClick={commit}
              disabled={!value.trim()}
              className="rounded px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50"
              style={{ background: 'var(--mars-color-primary)', color: '#fff' }}
            >
              Add
            </button>
          </div>

          {customModels.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {customModels.map((m) => (
                <span
                  key={m.value}
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-mono"
                  style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text-secondary)', border: '1px solid var(--mars-color-border)' }}
                >
                  {m.value}
                  <button
                    type="button"
                    onClick={() => onRemove(m.value)}
                    className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-red-500/20"
                    aria-label={`Remove ${m.value}`}
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ModelSelect({
  label,
  value,
  defaultValue,
  models,
  disabled,
  help,
  onChange,
}: {
  label: string;
  value: string | undefined;
  defaultValue: string;
  models: ModelOption[];
  disabled?: boolean;
  help?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium" style={{ color: disabled ? 'var(--mars-color-text-tertiary)' : 'var(--mars-color-text-secondary)' }}>
        {label}
        <span className="ml-1 font-normal opacity-60">(default: {defaultValue})</span>
      </label>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded border px-2 py-1.5 text-xs outline-none transition-colors disabled:opacity-50"
        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
      >
        <option value="">— use default ({defaultValue}) —</option>
        {models.map((m) => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </select>
      {help && (
        <p className="mt-1 text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>{help}</p>
      )}
    </div>
  );
}

function LimitInput({
  label,
  defaultValue,
  value,
  min,
  max,
  disabled,
  help,
  onChange,
}: {
  label: string;
  defaultValue: number;
  value: number | undefined;
  min: number;
  max: number;
  disabled?: boolean;
  help?: string;
  onChange: (v: number | null) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium" style={{ color: disabled ? 'var(--mars-color-text-tertiary)' : 'var(--mars-color-text-secondary)' }}>
        {label}
        <span className="ml-1 font-normal opacity-60">(default: {defaultValue})</span>
      </label>
      <input
        type="number"
        min={min}
        max={max}
        placeholder={String(defaultValue)}
        value={value ?? ''}
        onChange={(e) => {
          const v = e.target.value;
          if (v === '') onChange(null);
          else onChange(Number(v));
        }}
        disabled={disabled}
        className="w-full rounded border px-2 py-1.5 font-mono text-xs outline-none transition-colors disabled:opacity-50"
        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
      />
      {help && (
        <p className="mt-1 text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>{help}</p>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  help,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  help?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium" style={{ color: 'var(--mars-color-text-secondary)' }}>{label}</label>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || 0)))}
        className="w-full rounded border px-2 py-1.5 font-mono text-xs outline-none"
        style={{ backgroundColor: 'var(--mars-color-surface)', borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text)' }}
      />
      {help && (
        <p className="mt-1 text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>{help}</p>
      )}
    </div>
  );
}
