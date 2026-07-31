'use client';

import {
  CheckCircle2,
  Download,
  Eye,
  FileCode2,
  Loader2,
  Pencil,
  Play,
  RefreshCw,
  Save,
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
  onRegeneratePdf?: () => Promise<{ success: boolean; pdf_path?: string; backend_used?: string; error?: string } | null>;
  workDir: string;
  busy?: boolean;
}

type ViewMode = 'preview' | 'edit';

function downloadHtml(content: string) {
  if (typeof window === 'undefined' || !content) return;
  const blob = new Blob([content], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'newsletter.html';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function StageCard({
  taskId,
  stage,
  stageContent,
  consoleLines,
  modeConfig,
  onModeConfigChange,
  onExecute,
  onUpdateContent,
  onRegeneratePdf,
  workDir,
  busy,
}: Props) {
  const accent = STAGE_ACCENT[stage.stage_number] ?? '#8b5cf6';

  // Stage-output editor state. Reset whenever the stage's content arrives /
  // changes, so the textarea reflects the latest backend version.
  const [draft, setDraft] = useState<string>(stageContent?.content ?? '');
  const [view, setView] = useState<ViewMode>('preview');
  const [pdfStatus, setPdfStatus] = useState<{ success: boolean; pdf_path?: string; backend_used?: string; error?: string } | null>(null);
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

  // PDF / HTML surfaced on Stage 5.
  const reportHtml: string =
    (stageContent?.shared_state?.['report_html'] as string | undefined)
    ?? (stageContent?.content ?? draft);
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

      {/* Output preview / editor — only when stage has content. */}
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
                    onClick={() => downloadHtml(reportHtml)}
                    disabled={!reportHtml}
                  >
                    <FileCode2 size={13} /> Download HTML
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
          {pdfStatus && pdfStatus.success && pdfStatus.backend_used && (
            <div
              className="rounded-lg border px-3 py-2 text-xs"
              style={{
                borderColor: pdfStatus.backend_used === 'fpdf2' ? 'rgba(245, 158, 11, 0.4)' : 'rgba(34, 197, 94, 0.3)',
                backgroundColor: pdfStatus.backend_used === 'fpdf2' ? 'rgba(245, 158, 11, 0.08)' : 'rgba(34, 197, 94, 0.06)',
                color: pdfStatus.backend_used === 'fpdf2' ? '#fbbf24' : '#86efac',
              }}
            >
              PDF rendered with <span className="font-mono">{pdfStatus.backend_used}</span>
              {pdfStatus.backend_used === 'fpdf2' && ' (WeasyPrint unavailable — fallback)'}
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

        </div>
      )}
    </Card>
  );
}
