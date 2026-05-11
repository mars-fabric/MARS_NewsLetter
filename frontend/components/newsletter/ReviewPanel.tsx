'use client';

import { CheckCircle2, Eye, Link2, Pencil, Save, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { TextArea, TextInput } from '@/components/core/Input';
import { MarkdownRenderer } from '@/components/files/MarkdownRenderer';
import { LinkValidationResult, STAGE_ACCENT, StageContent } from '@/types/newsletter';

interface Props {
  stage: StageContent | null | undefined;
  onSave: (content: string) => Promise<void>;
  onRefine: (instruction: string, content: string) => Promise<string | null>;
  saving?: boolean;
}

export function ReviewPanel({ stage, onSave, onRefine, saving }: Props) {
  const [content, setContent] = useState<string>(stage?.content ?? '');
  const [tab, setTab] = useState<'preview' | 'edit'>('preview');
  const [refineMessage, setRefineMessage] = useState('');
  const [refining, setRefining] = useState(false);

  useEffect(() => {
    setContent(stage?.content ?? '');
  }, [stage?.stage_number, stage?.content]);

  async function handleRefine() {
    if (!refineMessage.trim()) return;
    setRefining(true);
    try {
      const next = await onRefine(refineMessage, content);
      if (next) {
        setContent(next);
        setRefineMessage('');
        setTab('preview');
      }
    } finally {
      setRefining(false);
    }
  }

  if (!stage) {
    return (
      <Card>
        <CardTitle>No content yet</CardTitle>
        <CardSubtitle>Run this stage first to see its output.</CardSubtitle>
      </Card>
    );
  }

  const accent = STAGE_ACCENT[stage.stage_number] ?? '#8b5cf6';

  return (
    <div className="space-y-3">
      <Card accent={accent} glow style={{ borderColor: `${accent}33` }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-9 w-9 items-center justify-center rounded-xl text-sm font-bold text-white"
              style={{
                background: `linear-gradient(135deg, ${accent}, ${accent}aa)`,
                boxShadow: `0 4px 12px ${accent}55`,
              }}
            >
              {stage.stage_number}
            </div>
            <div>
              <CardTitle>{stage.stage_name}</CardTitle>
              <CardSubtitle>Review, edit, or ask the model to refine.</CardSubtitle>
            </div>
          </div>

          {/* Modern segmented tabs */}
          <div
            className="flex rounded-lg p-1"
            style={{
              background: 'var(--mars-color-surface-sunken)',
              border: '1px solid var(--mars-color-border)',
            }}
          >
            <button
              onClick={() => setTab('preview')}
              className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-all"
              style={{
                background: tab === 'preview' ? 'var(--mars-color-surface-raised)' : 'transparent',
                color: tab === 'preview' ? accent : 'var(--mars-color-text-tertiary)',
                boxShadow: tab === 'preview' ? `0 0 10px ${accent}33` : 'none',
              }}
            >
              <Eye size={13} /> Preview
            </button>
            <button
              onClick={() => setTab('edit')}
              className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-all"
              style={{
                background: tab === 'edit' ? 'var(--mars-color-surface-raised)' : 'transparent',
                color: tab === 'edit' ? accent : 'var(--mars-color-text-tertiary)',
                boxShadow: tab === 'edit' ? `0 0 10px ${accent}33` : 'none',
              }}
            >
              <Pencil size={13} /> Edit
            </button>
          </div>
        </div>

        <div className="mt-3">
          {tab === 'preview' ? (
            <div
              className="prose max-w-none rounded-lg p-4"
              style={{
                background: 'var(--mars-color-surface-sunken)',
                border: '1px solid var(--mars-color-border)',
                color: 'var(--mars-color-text)',
              }}
            >
              <MarkdownRenderer source={content} />
            </div>
          ) : (
            <TextArea value={content} onChange={(e) => setContent(e.target.value)} rows={20} />
          )}
        </div>

        <div className="mt-3 flex justify-end">
          <Button onClick={() => onSave(content)} loading={saving}>
            <Save size={13} /> Save edits
          </Button>
        </div>
      </Card>

      {stage.link_validation && stage.link_validation.length > 0 && (
        <LinkValidationCard rows={stage.link_validation} />
      )}

      <Card accent="#8b5cf6">
        <div className="flex items-center gap-2">
          <Sparkles size={14} style={{ color: '#8b5cf6' }} />
          <CardTitle>Refine with the model</CardTitle>
        </div>
        <CardSubtitle>Describe what to change. The model edits in place using only the curated set.</CardSubtitle>
        <div className="mt-3 flex flex-col gap-2 md:flex-row">
          <TextInput
            placeholder='e.g. "Tighten the executive summary to 4 bullets and link the regulator citations."'
            value={refineMessage}
            onChange={(e) => setRefineMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                void handleRefine();
              }
            }}
          />
          <Button onClick={handleRefine} loading={refining} disabled={!refineMessage.trim()}>
            <Sparkles size={13} /> Refine
          </Button>
        </div>
      </Card>
    </div>
  );
}

function LinkValidationCard({ rows }: { rows: LinkValidationResult[] }) {
  const counts = {
    official: rows.filter((r) => r.authority_tier === 'official').length,
    authority: rows.filter((r) => r.authority_tier === 'authority').length,
    unknown: rows.filter((r) => r.authority_tier === 'unknown').length,
  };

  const tierColor = (tier: string) =>
    tier === 'official' ? '#22c55e' : tier === 'authority' ? '#06b6d4' : '#f59e0b';

  return (
    <Card>
      <div className="flex items-center gap-2">
        <Link2 size={14} style={{ color: 'var(--mars-color-text-tertiary)' }} />
        <CardTitle>User-supplied link validation</CardTitle>
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-[11px]">
        <span className="flex items-center gap-1" style={{ color: '#22c55e' }}>
          <CheckCircle2 size={12} /> {counts.official} official
        </span>
        <span className="flex items-center gap-1" style={{ color: '#06b6d4' }}>
          {counts.authority} authority
        </span>
        <span className="flex items-center gap-1" style={{ color: '#f59e0b' }}>
          {counts.unknown} unknown
        </span>
      </div>
      <div
        className="mt-3 max-h-60 overflow-auto rounded-lg"
        style={{ border: '1px solid var(--mars-color-border)' }}
      >
        <table className="w-full text-left text-[11px]">
          <thead style={{ background: 'var(--mars-color-surface-overlay)', color: 'var(--mars-color-text-tertiary)' }}>
            <tr>
              <th className="px-2.5 py-2 font-semibold">URL</th>
              <th className="px-2.5 py-2 font-semibold">Status</th>
              <th className="px-2.5 py-2 font-semibold">Tier</th>
              <th className="px-2.5 py-2 font-semibold">Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.url} style={{ borderTop: '1px solid var(--mars-color-border)' }}>
                <td className="px-2.5 py-2">
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: 'var(--mars-color-primary)' }}
                    className="hover:underline"
                  >
                    {r.domain || r.url}
                  </a>
                </td>
                <td className="px-2.5 py-2" style={{ color: r.reachable ? 'var(--mars-color-success)' : 'var(--mars-color-danger)' }}>
                  {r.reachable ? `OK ${r.status_code ?? ''}` : 'unreachable'}
                </td>
                <td className="px-2.5 py-2">
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                    style={{
                      background: `${tierColor(r.authority_tier)}1f`,
                      color: tierColor(r.authority_tier),
                      border: `1px solid ${tierColor(r.authority_tier)}55`,
                    }}
                  >
                    {r.authority_tier}
                  </span>
                </td>
                <td className="px-2.5 py-2" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                  {r.notes ?? (r.matched_industry ? `matched: ${r.matched_industry}` : '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
