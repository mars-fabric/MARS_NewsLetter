'use client';

import { Download, FileCode2, FileText, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { MarkdownRenderer } from '@/components/files/MarkdownRenderer';
import { STAGE_ACCENT, StageContent, TaskState } from '@/types/newsletter';

interface Props {
  task: TaskState;
  finalStage: StageContent | null | undefined;
  onRegeneratePdf: () => Promise<{ success: boolean; pdf_path?: string; error?: string } | null>;
}

function slugify(value: string): string {
  return (value || 'newsletter')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 80) || 'newsletter';
}

function downloadMarkdown(title: string, content: string) {
  if (typeof window === 'undefined' || !content) return;
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${slugify(title)}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportPanel({ task, finalStage, onRegeneratePdf }: Props) {
  const [pdfStatus, setPdfStatus] = useState<{ success: boolean; pdf_path?: string; error?: string } | null>(null);
  const [working, setWorking] = useState(false);

  if (!finalStage || finalStage.status !== 'completed') {
    return (
      <Card>
        <CardTitle>Final report</CardTitle>
        <CardSubtitle>Complete Stage 5 to view the final newsletter and download the PDF.</CardSubtitle>
      </Card>
    );
  }

  const pdfPath =
    pdfStatus?.pdf_path
    ?? (finalStage.shared_state?.['pdf_path'] as string | undefined)
    ?? null;

  async function regenerate() {
    setWorking(true);
    try {
      const res = await onRegeneratePdf();
      if (res) setPdfStatus(res);
    } finally {
      setWorking(false);
    }
  }

  const accent = STAGE_ACCENT[5];

  return (
    <div className="space-y-4">
      <Card accent={accent} glow style={{ borderColor: `${accent}33` }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-xl text-white"
              style={{
                background: `linear-gradient(135deg, ${accent}, ${accent}aa)`,
                boxShadow: `0 4px 16px ${accent}66`,
              }}
            >
              <FileText className="h-5 w-5" />
            </div>
            <div>
              <CardTitle>Final newsletter</CardTitle>
              <CardSubtitle>{task.title ?? 'Untitled'} · ready to share</CardSubtitle>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={regenerate} loading={working}>
              <RefreshCw size={13} /> Regenerate PDF
            </Button>
            <Button
              variant="secondary"
              onClick={() => downloadMarkdown(task.title ?? 'newsletter', finalStage.content ?? '')}
              disabled={!finalStage.content}
            >
              <FileCode2 size={13} /> Download Markdown
            </Button>
            {pdfPath && (
              <Button
                onClick={() => {
                  const url = `/api/newsletter/files/download?work_dir=${encodeURIComponent(task.work_dir ?? '')}&rel_path=${encodeURIComponent(pdfPath.replace((task.work_dir ?? '') + '/', ''))}`;
                  window.open(url, '_blank');
                }}
              >
                <Download size={13} /> Download PDF
              </Button>
            )}
          </div>
        </div>

        {pdfStatus && !pdfStatus.success && (
          <div
            className="mt-3 rounded-lg border px-3 py-2 text-xs"
            style={{
              borderColor: 'rgba(239, 68, 68, 0.4)',
              backgroundColor: 'rgba(239, 68, 68, 0.08)',
              color: '#fca5a5',
            }}
          >
            PDF generation failed: {pdfStatus.error ?? 'unknown error'}
          </div>
        )}

        <div
          className="prose mt-4 max-w-none rounded-lg p-5"
          style={{
            background: 'var(--mars-color-surface-sunken)',
            border: '1px solid var(--mars-color-border)',
            color: 'var(--mars-color-text)',
          }}
        >
          <MarkdownRenderer source={finalStage.content ?? ''} />
        </div>
      </Card>
    </div>
  );
}
