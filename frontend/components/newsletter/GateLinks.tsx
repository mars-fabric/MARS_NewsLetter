'use client';

import { Link2, Pin, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { LinkAction, LinkPriority } from '@/types/newsletter';

interface Props {
  /** Stage-2 markdown content (source collection) — links are extracted from it. */
  sourceMarkdown: string;
  busy?: boolean;
  onSave: (priorities: LinkPriority[], addUrls: string[], minRelevance: number | null) => Promise<void>;
}

const URL_RE = /https?:\/\/[^\s)\]"'<>]+/g;

function extractUrls(md: string): string[] {
  const found = new Set<string>();
  for (const m of md.matchAll(URL_RE)) {
    found.add(m[0].replace(/[.,;:!?'")\]>]+$/, ''));
  }
  return Array.from(found);
}

const ACTION_STYLE: Record<LinkAction, string> = {
  pin: '#22c55e',
  boost: '#3b82f6',
  normal: '#94a3b8',
  exclude: '#ef4444',
};

/**
 * Gate A — user link prioritization, shown before Stage 3 (Curation).
 * Lets the user pin, boost, or exclude any discovered link, inject extra URLs,
 * and relax the curation drop threshold so nothing useful gets over-filtered.
 */
export function GateLinks({ sourceMarkdown, busy, onSave }: Props) {
  const urls = useMemo(() => extractUrls(sourceMarkdown), [sourceMarkdown]);
  const [actions, setActions] = useState<Record<string, LinkAction>>({});
  const [addRaw, setAddRaw] = useState('');
  const [minRelevance, setMinRelevance] = useState<number>(0.3);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setActions((prev) => {
      const next = { ...prev };
      for (const u of urls) if (!next[u]) next[u] = 'normal';
      return next;
    });
  }, [urls]);

  const cycle = (u: string) => {
    const order: LinkAction[] = ['normal', 'pin', 'boost', 'exclude'];
    setActions((p) => {
      const cur = p[u] ?? 'normal';
      const nxt = order[(order.indexOf(cur) + 1) % order.length];
      return { ...p, [u]: nxt };
    });
    setSaved(false);
  };

  const save = async () => {
    const priorities: LinkPriority[] = Object.entries(actions)
      .filter(([, a]) => a !== 'normal')
      .map(([url, action]) => ({ url, action }));
    const addUrls = addRaw
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter((s) => s.startsWith('http'));
    await onSave(priorities, addUrls, minRelevance);
    setSaved(true);
  };

  const counts = useMemo(() => {
    const c = { pin: 0, boost: 0, exclude: 0 };
    for (const a of Object.values(actions)) if (a in c) (c as Record<string, number>)[a]++;
    return c;
  }, [actions]);

  return (
    <Card accent="#3b82f6" style={{ borderColor: '#3b82f633' }}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle><Link2 className="mr-1.5 inline h-4 w-4" />Gate A · Prioritize sources</CardTitle>
          <CardSubtitle>
            {urls.length} link(s) discovered. Click a link to cycle Normal → Pin → Boost → Exclude.
            Pinned links always survive curation. Then run Stage 3.
          </CardSubtitle>
        </div>
        <div className="flex gap-2 text-[11px]" style={{ color: 'var(--mars-color-text-secondary)' }}>
          <span style={{ color: ACTION_STYLE.pin }}>Pin {counts.pin}</span>
          <span style={{ color: ACTION_STYLE.boost }}>Boost {counts.boost}</span>
          <span style={{ color: ACTION_STYLE.exclude }}>Exclude {counts.exclude}</span>
        </div>
      </div>

      <div className="mt-3 max-h-64 space-y-1 overflow-auto rounded-lg border p-2"
        style={{ borderColor: 'var(--mars-color-border)' }}>
        {urls.length === 0 && (
          <p className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            No links found in the Stage 2 output yet.
          </p>
        )}
        {urls.map((u) => {
          const a = actions[u] ?? 'normal';
          return (
            <button
              key={u}
              onClick={() => cycle(u)}
              className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-white/5"
              style={{ textDecoration: a === 'exclude' ? 'line-through' : 'none' }}
            >
              <span
                className="inline-block h-2 w-2 flex-shrink-0 rounded-full"
                style={{ background: ACTION_STYLE[a] }}
              />
              {a === 'pin' && <Pin className="h-3 w-3 flex-shrink-0" style={{ color: ACTION_STYLE.pin }} />}
              {a === 'exclude' && <X className="h-3 w-3 flex-shrink-0" style={{ color: ACTION_STYLE.exclude }} />}
              <span className="truncate" style={{ color: 'var(--mars-color-text-secondary)' }}>{u}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
          Add trusted URLs (auto-pinned, space/comma separated)
          <textarea
            rows={2}
            value={addRaw}
            onChange={(e) => { setAddRaw(e.target.value); setSaved(false); }}
            placeholder="https://vendor.com/press/…"
            className="mt-1 w-full rounded border bg-transparent p-2 text-[11px]"
            style={{ borderColor: 'var(--mars-color-border)' }}
          />
        </label>
        <label className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
          Curation drop threshold: <strong>{minRelevance.toFixed(2)}</strong> (lower keeps more)
          <input
            type="range" min={0} max={1} step={0.05}
            value={minRelevance}
            onChange={(e) => { setMinRelevance(Number(e.target.value)); setSaved(false); }}
            className="mt-2 w-full"
          />
        </label>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <Button onClick={save} disabled={busy}>
          {saved ? 'Priorities saved ✓' : 'Save priorities'}
        </Button>
        {saved && (
          <span className="text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Now run Stage 3 to apply them.
          </span>
        )}
      </div>
    </Card>
  );
}
