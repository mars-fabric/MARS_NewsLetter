'use client';

import { Download, FileJson, FileText, Globe } from 'lucide-react';
import { useMemo } from 'react';

import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { getApiUrl } from '@/lib/config';

interface Props {
  /** PDF path returned from Stage 5 (used only to know PDF is ready). */
  pdfPath?: string | null;
  workDir: string;
  outputFiles: string[] | null;
}

function relTo(workDir: string, abs: string): string {
  if (workDir && abs.startsWith(workDir)) {
    return abs.slice(workDir.length).replace(/^\/+/, '');
  }
  const parts = abs.split('/');
  return parts.slice(-2).join('/');
}

/**
 * Stage 5 report view — PDF-only.
 *
 * The LLM enhance pass was removed from the Stage-5 pipeline because it
 * corrupted link URLs; the deterministic link_fix node replaced it. The
 * primary artifact is now the PDF (generated from the verified JSON document).
 * HTML is still built as a download artifact but is no longer shown in an
 * iframe to avoid confusing users with two separate views.
 */
export function ReportView({ pdfPath, workDir, outputFiles }: Props) {
  const downloads = useMemo(() => {
    const files = outputFiles ?? [];
    const find = (suffix: string) => files.find((f) => f.endsWith(suffix));
    const build = (abs?: string) =>
      abs
        ? getApiUrl(
            `/api/newsletter/files/download?work_dir=${encodeURIComponent(workDir)}&rel_path=${encodeURIComponent(relTo(workDir, abs))}`,
          )
        : null;
    return {
      pdf:  build(files.find((f) => f.endsWith('.pdf'))),
      html: build(find('newsletter_final.html')),
      json: build(find('report.json')),
    };
  }, [outputFiles, workDir]);

  const hasPdf = Boolean(downloads.pdf);

  return (
    <Card accent="#f59e0b" style={{ borderColor: '#f59e0b33' }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Dynamic Report</CardTitle>
          <CardSubtitle>
            Link-validated newsletter — rendered from a structured JSON document.
          </CardSubtitle>
        </div>
        <div className="flex flex-wrap gap-2">
          {downloads.pdf && (
            <a
              href={downloads.pdf}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white"
              style={{ background: 'linear-gradient(135deg, #f59e0b, #f59e0bcc)' }}
            >
              <Download className="h-3.5 w-3.5" /> Download PDF
            </a>
          )}
          {downloads.html && (
            <a
              href={downloads.html}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
              style={{ border: '1px solid var(--mars-color-border)', color: 'var(--mars-color-text-secondary)' }}
            >
              <Globe className="h-3.5 w-3.5" /> HTML
            </a>
          )}
          {downloads.json && (
            <a
              href={downloads.json}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
              style={{ border: '1px solid var(--mars-color-border)', color: 'var(--mars-color-text-secondary)' }}
            >
              <FileJson className="h-3.5 w-3.5" /> JSON
            </a>
          )}
        </div>
      </div>

      {/* PDF ready state */}
      <div
        className="mt-3 flex min-h-[120px] items-center justify-center rounded-lg border"
        style={{ borderColor: 'var(--mars-color-border)', background: hasPdf ? '#fef9f0' : 'transparent' }}
      >
        {hasPdf ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <div
              className="flex h-12 w-12 items-center justify-center rounded-full"
              style={{ background: 'linear-gradient(135deg, #f59e0b22, #f59e0b44)' }}
            >
              <Download className="h-6 w-6" style={{ color: '#f59e0b' }} />
            </div>
            <p className="text-sm font-semibold" style={{ color: '#92400e' }}>
              Report ready
            </p>
            <a
              href={downloads.pdf!}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white"
              style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}
            >
              <Download className="h-4 w-4" /> Open PDF
            </a>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            <FileText className="h-4 w-4" /> Run Stage 5 to build the report.
          </div>
        )}
      </div>
    </Card>
  );
}
