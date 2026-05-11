'use client';

import {
  Award,
  CheckCircle2,
  Download,
  Eye,
  FileCode2,
  Loader2,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { TextArea } from '@/components/core/Input';
import { MarkdownRenderer } from '@/components/files/MarkdownRenderer';
import { ConsoleLine } from '@/hooks/useNewsletterTask';
import {
  STAGE_ACCENT,
  STAGE_DESCRIPTIONS,
  STAGE_NAMES,
  ScoreCard as ScoreCardType,
  StageContent,
  StageInfo,
  StageModeConfig,
} from '@/types/newsletter';

import { ConsoleOutput } from './ConsoleOutput';
import { StageAdvancedSettings } from './StageAdvancedSettings';

interface Props {
  taskId: string;
  stage: StageInfo;
  stageContent: StageContent | null;
  consoleLines: ConsoleLine[];
  modeConfig: StageModeConfig;
  onModeConfigChange: (next: StageModeConfig) => void;
  onExecute: () => void;
  onUpdateContent: (content: string) => Promise<void>;
  onRefine: (instruction: string, content: string) => Promise<string | null>;
  onRegeneratePdf?: () => Promise<{ success: boolean; pdf_path?: string; error?: string } | null>;
  workDir: string;
  busy?: boolean;
}

type ViewMode = 'preview' | 'edit';

function downloadMarkdown(content: string) {
  if (typeof window === 'undefined' || !content) return;
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'newsletter.md';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function StageCard({
  taskId: _taskId,
  stage,
  stageContent,
  consoleLines,
  modeConfig,
  onModeConfigChange,
  onExecute,
  onUpdateContent,
  onRefine,
  onRegeneratePdf,
  workDir,
  busy,
}: Props) {
  const accent = STAGE_ACCENT[stage.stage_number] ?? '#8b5cf6';

  // Stage-output editor state. Reset whenever the stage's content arrives /
  // changes, so the textarea reflects the latest backend version.
  const [draft, setDraft] = useState<string>(stageContent?.content ?? '');
  const [view, setView] = useState<ViewMode>('preview');
  const [refineMessage, setRefineMessage] = useState('');
  const [refining, setRefining] = useState(false);
  const [pdfStatus, setPdfStatus] = useState<{ success: boolean; pdf_path?: string; error?: string } | null>(null);
  const [regeneratingPdf, setRegeneratingPdf] = useState(false);

  useEffect(() => {
    setDraft(stageContent?.content ?? '');
  }, [stage.stage_number, stageContent?.content]);

  const linesForStage = useMemo(
    () => consoleLines.filter((l) => l.stage_num === stage.stage_number),
    [consoleLines, stage.stage_number],
  );

  const isRunning = stage.status === 'running';
  const isDone = stage.status === 'completed';
  const isFailed = stage.status === 'failed';
  const StatusIcon = isDone ? CheckCircle2 : isFailed ? XCircle : isRunning ? Loader2 : Play;
  const statusColor = isDone
    ? 'var(--mars-color-success)'
    : isFailed
      ? 'var(--mars-color-danger)'
      : accent;

  async function saveContent() {
    await onUpdateContent(draft);
    setView('preview');
  }

  async function handleRefine() {
    if (!refineMessage.trim()) return;
    setRefining(true);
    try {
      const next = await onRefine(refineMessage, draft);
      if (next) {
        setDraft(next);
        setRefineMessage('');
        setView('preview');
      }
    } finally {
      setRefining(false);
    }
  }

  async function handleRegenerate() {
    if (!onRegeneratePdf) return;
    setRegeneratingPdf(true);
    try {
      const r = await onRegeneratePdf();
      if (r) setPdfStatus(r);
    } finally {
      setRegeneratingPdf(false);
    }
  }

  // PDF / score card surfaced on Stage 5.
  const scoreCard = (stageContent?.score_card ?? null) as ScoreCardType | null;
  const pdfPath: string | null =
    pdfStatus?.pdf_path
    ?? (stageContent?.shared_state?.['pdf_path'] as string | undefined)
    ?? null;

  return (
    <Card accent={accent} glow style={{ borderColor: `${accent}33` }}>
      {/* Header — stage number + name + description + status pill + execute button */}
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
              <span
                className="ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]"
                style={{
                  background: 'var(--mars-color-surface-overlay)',
                  color: statusColor,
                  border: `1px solid ${statusColor}55`,
                }}
              >
                <StatusIcon className={`h-3 w-3 ${isRunning ? 'animate-spin' : ''}`} />
                {stage.status}
              </span>
              {stage.mode && (
                <span
                  className="ml-1.5 inline-block rounded px-1.5 py-0.5 font-mono text-[10px]"
                  style={{ background: 'var(--mars-color-surface-overlay)', color: accent }}
                >
                  mode · {stage.mode}
                </span>
              )}
              {typeof stage.cost_usd === 'number' && stage.cost_usd > 0 && (
                <span
                  className="ml-1.5 inline-block rounded px-1.5 py-0.5 font-mono text-[10px]"
                  style={{
                    background: 'rgba(34,197,94,0.12)',
                    color: '#86efac',
                    border: '1px solid rgba(34,197,94,0.25)',
                  }}
                  title="Cost spent on this stage"
                >
                  ${stage.cost_usd.toFixed(4)}
                </span>
              )}
            </CardTitle>
            <CardSubtitle>{STAGE_DESCRIPTIONS[stage.stage_number]}</CardSubtitle>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={isDone ? 'secondary' : 'primary'}
            onClick={onExecute}
            disabled={busy || isRunning}
            loading={isRunning}
          >
            {isDone ? (
              <>
                <RefreshCw size={14} /> Re-run
              </>
            ) : (
              <>
                <Play size={14} /> Run stage {stage.stage_number}
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Error banner */}
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

      {/* Per-stage settings drawer (mode + every cmbagent knob). */}
      <div className="mt-4">
        <StageAdvancedSettings
          value={modeConfig}
          onChange={onModeConfigChange}
          stages={[stage.stage_number]}
        />
      </div>

      {/* Live console — always visible for stages 2-5, especially during runs. */}
      <div className="mt-4">
        <ConsoleOutput
          lines={linesForStage}
          accent={accent}
          title={`Stage ${stage.stage_number} · ${STAGE_NAMES[stage.stage_number]}`}
          status={
            isRunning
              ? 'streaming'
              : isDone
                ? 'done'
                : isFailed
                  ? 'error'
                  : 'idle'
          }
          height={isRunning ? 360 : 220}
        />
      </div>

      {/* Score card — Stage 5 only, when output is available. */}
      {stage.stage_number === 5 && isDone && scoreCard && (
        <div className="mt-4">
          <ScoreCardView score={scoreCard} accent={accent} />
        </div>
      )}

      {/* Output preview / editor / refine — only when stage has content. */}
      {isDone && stageContent && (
        <div className="mt-4 space-y-3">
          {/* Preview / Edit toggle + actions */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              className="flex rounded-lg p-1"
              style={{
                background: 'var(--mars-color-surface-sunken)',
                border: '1px solid var(--mars-color-border)',
              }}
            >
              <button
                onClick={() => setView('preview')}
                className="flex items-center gap-1 rounded-md px-3 py-1 text-[11px] font-semibold transition-all"
                style={{
                  background: view === 'preview' ? `${accent}22` : 'transparent',
                  color: view === 'preview' ? accent : 'var(--mars-color-text-secondary)',
                }}
              >
                <Eye size={12} /> Preview
              </button>
              <button
                onClick={() => setView('edit')}
                className="flex items-center gap-1 rounded-md px-3 py-1 text-[11px] font-semibold transition-all"
                style={{
                  background: view === 'edit' ? `${accent}22` : 'transparent',
                  color: view === 'edit' ? accent : 'var(--mars-color-text-secondary)',
                }}
              >
                <Pencil size={12} /> Edit
              </button>
            </div>
            <div className="flex items-center gap-2">
              {view === 'edit' && (
                <Button variant="secondary" onClick={saveContent} disabled={busy}>
                  <Save size={13} /> Save & cascade
                </Button>
              )}
              {/* Stage 5: Markdown + PDF download */}
              {stage.stage_number === 5 && onRegeneratePdf && (
                <>
                  <Button variant="secondary" onClick={handleRegenerate} loading={regeneratingPdf}>
                    <RefreshCw size={13} /> Regenerate PDF
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => downloadMarkdown(stageContent?.content ?? draft)}
                    disabled={!(stageContent?.content || draft)}
                  >
                    <FileCode2 size={13} /> Download Markdown
                  </Button>
                  {pdfPath && (
                    <Button
                      onClick={() => {
                        const rel = pdfPath.replace((workDir ?? '') + '/', '');
                        const url = `/api/newsletter/files/download?work_dir=${encodeURIComponent(workDir)}&rel_path=${encodeURIComponent(rel)}`;
                        window.open(url, '_blank');
                      }}
                    >
                      <Download size={13} /> Download PDF
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>

          {pdfStatus && !pdfStatus.success && (
            <div
              className="rounded-lg border px-3 py-2 text-xs"
              style={{
                borderColor: 'rgba(239, 68, 68, 0.4)',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                color: '#fca5a5',
              }}
            >
              PDF generation failed: {pdfStatus.error ?? 'unknown error'}
            </div>
          )}

          {/* Markdown content */}
          {view === 'preview' ? (
            <div
              className="prose max-w-none rounded-lg p-5"
              style={{
                background: 'var(--mars-color-surface-sunken)',
                border: '1px solid var(--mars-color-border)',
                color: 'var(--mars-color-text)',
              }}
            >
              <MarkdownRenderer source={draft} />
            </div>
          ) : (
            <TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={24}
              className="font-mono text-xs"
              placeholder="Stage output (markdown)…"
            />
          )}

          {/* Refine row */}
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={refineMessage}
              onChange={(e) => setRefineMessage(e.target.value)}
              placeholder={`Ask the model to refine this ${STAGE_NAMES[stage.stage_number].toLowerCase()}…`}
              className="flex-1 min-w-[260px] rounded-lg border px-3 py-2 text-xs outline-none"
              style={{
                backgroundColor: 'var(--mars-color-surface)',
                borderColor: 'var(--mars-color-border)',
                color: 'var(--mars-color-text)',
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void handleRefine();
                }
              }}
            />
            <Button onClick={handleRefine} loading={refining} disabled={!refineMessage.trim() || refining}>
              <Sparkles size={13} /> Refine
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function ScoreCardView({ score, accent }: { score: ScoreCardType; accent: string }) {
  const verdictColor =
    score.verdict === 'production-ready'
      ? '#22c55e'
      : score.verdict === 'reject'
        ? '#ef4444'
        : '#f59e0b';
  const subScores: { label: string; value: number | null | undefined }[] = [
    { label: 'Citations', value: score.citation_score },
    { label: 'Factual fidelity', value: score.factual_fidelity_score },
    { label: 'Coverage', value: score.coverage_score },
    { label: 'Structural completeness', value: score.structural_completeness_score },
  ];
  return (
    <div
      className="overflow-hidden rounded-xl border"
      style={{
        borderColor: `${accent}55`,
        background: `linear-gradient(135deg, ${accent}10, var(--mars-color-surface-raised))`,
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.04), 0 6px 18px -6px ${accent}55`,
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-3">
          <Award className="h-5 w-5" style={{ color: accent }} />
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
              Newsletter quality score
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tabular-nums" style={{ color: 'var(--mars-color-text)' }}>
                {score.authenticity_score}
              </span>
              <span className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>/ 100</span>
            </div>
          </div>
        </div>
        <span
          className="rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wider"
          style={{
            background: `${verdictColor}22`,
            color: verdictColor,
            border: `1px solid ${verdictColor}55`,
            boxShadow: `0 0 10px ${verdictColor}33`,
          }}
        >
          {score.verdict}
        </span>
      </div>

      <div className="grid gap-2 px-4 pb-4 md:grid-cols-4">
        {subScores.map((s) => (
          <div
            key={s.label}
            className="rounded-lg p-2"
            style={{ background: 'var(--mars-color-surface-sunken)', border: '1px solid var(--mars-color-border)' }}
          >
            <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
              {s.label}
            </div>
            <div className="font-mono text-sm tabular-nums" style={{ color: 'var(--mars-color-text)' }}>
              {s.value == null ? 'n/a' : `${s.value}`}
            </div>
          </div>
        ))}
      </div>

      {score.suggestions && score.suggestions.length > 0 && (
        <div
          className="px-4 pb-4"
          style={{ borderTop: '1px solid var(--mars-color-border)' }}
        >
          <div className="mt-3 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Reviewer suggestions
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
            {score.suggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {score.notes && (
        <div className="px-4 pb-4 text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
          <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Reviewer notes
          </div>
          <div className="mt-1">{score.notes}</div>
        </div>
      )}
    </div>
  );
}
