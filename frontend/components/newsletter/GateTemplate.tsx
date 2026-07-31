'use client';

import { GripVertical, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { SectionDepth, SectionSpecRequest } from '@/types/newsletter';

interface Props {
  /** Optional shape hint from Stage 1 used to seed the default template. */
  shapeHint?: string | null;
  busy?: boolean;
  onSave: (sections: SectionSpecRequest[], tone: string | null, audience: string | null) => Promise<void>;
}

/** Length option maps to a backend SectionDepth + an optional word_count. */
interface LengthOption {
  value: string;         // UI key
  depth: SectionDepth;   // backend depth value
  label: string;
  color: string;
  hint: string;
  wordCount?: number;    // explicit override (for custom)
}

const LENGTH_OPTIONS: LengthOption[] = [
  { value: 'short',    depth: 'light',    color: '#94a3b8', label: 'Short',          hint: '~180 words — concise summary'          },
  { value: 'standard', depth: 'standard', color: '#3b82f6', label: 'Standard',       hint: '~340 words — structured analysis'       },
  { value: 'deep',     depth: 'deep',     color: '#8b5cf6', label: 'Deep Research',  hint: '~650 words — cmbagent multi-step research' },
  { value: 'custom',   depth: 'standard', color: '#10b981', label: 'Custom',         hint: 'Set your own word count'                },
];

const LOCKED_TITLES = new Set(['Executive Summary', 'Sources']);

/**
 * The 22 canonical newsletter sections (mirrors backend
 * `constants.CANONICAL_HEADINGS`). Offered as a dropdown so the user can pick a
 * predefined, battle-tested section — or type any custom name they prefer.
 */
const CANONICAL_SECTION_NAMES: string[] = [
  'Newsletter Metadata',
  "Editor's Note",
  'Executive Summary',
  'TL;DR — Key Takeaways',
  'Industry & Subdomain Focus',
  'Top Story of the Period',
  'Secondary Major Story',
  'Other Notable Headlines',
  'Subdomain Highlights',
  'Releases & Announcements',
  'Trend Intelligence',
  'Audience-Centric Analysis',
  'Focus Topic Deep Dive',
  'Source-Driven Insights',
  'Data & Evidence',
  'Quotes & Opinions',
  'Tools & Resources',
  'Action & Utility',
  'Forward-Looking Intelligence',
  'Transparency & Methodology',
  'Compliance & Trust',
  'Closure',
];

const DEFAULT_SECTIONS: SectionSpecRequest[] = [
  { title: 'Executive Summary', depth: 'standard', points: null, guidance: 'The most important developments in the window.' },
  { title: 'Sources',           depth: 'light',    points: null, guidance: 'Consolidated list of all cited sources with working links.' },
];

const isLocked = (title: string) => LOCKED_TITLES.has(title.trim());

/** Derive the length option key from a section. */
function lengthOf(s: SectionSpecRequest): string {
  if (s.word_count != null) return 'custom';
  if (s.depth === 'light') return 'short';
  if (s.depth === 'deep')  return 'deep';
  return 'standard';
}

/**
 * Gate B — user report template, shown before Stage 4 (Generation).
 * Replaces the fixed 22-section layout. The user chooses exactly which
 * sections to produce, how long each should be, and (optionally) a custom
 * word count. Deep sections trigger a cmbagent deep_research pre-pass.
 */
export function GateTemplate({ shapeHint, busy, onSave }: Props) {
  const [sections, setSections] = useState<SectionSpecRequest[]>(() => {
    if (shapeHint && shapeHint.trim()) {
      const custom = shapeHint.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean)
        .filter((t) => !isLocked(t))
        .map((t) => ({ title: t, depth: 'standard' as SectionDepth, points: null, guidance: '' }));
      return [DEFAULT_SECTIONS[0], ...custom, DEFAULT_SECTIONS[1]];
    }
    return DEFAULT_SECTIONS;
  });
  const [tone, setTone] = useState('');
  const [audience, setAudience] = useState('');
  const [saved, setSaved] = useState(false);

  const update = (i: number, patch: Partial<SectionSpecRequest>) => {
    setSections((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
    setSaved(false);
  };

  const setLength = (i: number, opt: LengthOption) => {
    update(i, {
      depth: opt.depth,
      word_count: opt.value === 'custom' ? (sections[i].word_count ?? 400) : undefined,
    });
  };

  const remove = (i: number) => {
    setSections((p) => (isLocked(p[i]?.title) ? p : p.filter((_, idx) => idx !== i)));
    setSaved(false);
  };

  const add = () => {
    setSections((p) => {
      const insertAt = p.length > 0 && isLocked(p[p.length - 1].title) ? p.length - 1 : p.length;
      const next = [...p];
      next.splice(insertAt, 0, { title: '', depth: 'standard', points: null, guidance: '' });
      return next;
    });
    setSaved(false);
  };

  /** Add one of the 22 predefined sections by name (skips duplicates). */
  const addPredefined = (title: string) => {
    if (!title) return;
    setSections((p) => {
      if (p.some((s) => s.title.trim().toLowerCase() === title.toLowerCase())) return p;
      const insertAt = p.length > 0 && isLocked(p[p.length - 1].title) ? p.length - 1 : p.length;
      const next = [...p];
      next.splice(insertAt, 0, { title, depth: 'standard', points: null, guidance: '' });
      return next;
    });
    setSaved(false);
  };

  const move = (i: number, dir: -1 | 1) => {
    setSections((p) => {
      const j = i + dir;
      if (j < 0 || j >= p.length) return p;
      if (isLocked(p[i].title) || isLocked(p[j].title)) return p;
      const next = [...p];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
    setSaved(false);
  };

  const save = async () => {
    const clean = sections.filter((s) => s.title.trim());
    if (clean.length === 0) return;
    await onSave(clean, tone.trim() || null, audience.trim() || null);
    setSaved(true);
  };

  return (
    <Card accent="#8b5cf6" style={{ borderColor: '#8b5cf633' }}>
      <CardTitle>Gate B · Design your report</CardTitle>
      <CardSubtitle>
        Choose exactly which sections to include and how long each should be.
        Click a section title to <strong>pick one of the 22 standard sections</strong> from the
        list, or just type your own custom name.
        <strong> Deep Research</strong> sections run a cmbagent multi-step analysis — use sparingly.
        Executive Summary and Sources are always included.
      </CardSubtitle>

      {/* Shared datalist — powers the section-name dropdown on every title input. */}
      <datalist id="canonical-section-names">
        {CANONICAL_SECTION_NAMES.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <div className="mt-3 space-y-2">
        {sections.map((s, i) => {
          const locked = isLocked(s.title);
          const currentLength = lengthOf(s);
          return (
          <div key={i} className="rounded-lg border p-2" style={{ borderColor: locked ? '#8b5cf655' : 'var(--mars-color-border)', background: locked ? '#8b5cf60a' : 'transparent' }}>
            <div className="flex items-center gap-2">
              <div className="flex flex-col">
                <button onClick={() => move(i, -1)} disabled={locked} className="text-[10px] opacity-60 hover:opacity-100 disabled:opacity-20">▲</button>
                <button onClick={() => move(i, 1)} disabled={locked} className="text-[10px] opacity-60 hover:opacity-100 disabled:opacity-20">▼</button>
              </div>
              <GripVertical className="h-4 w-4 flex-shrink-0 opacity-40" />
              <input
                value={s.title}
                onChange={(e) => update(i, { title: e.target.value })}
                placeholder="Pick a section or type a custom name"
                readOnly={locked}
                list={locked ? undefined : 'canonical-section-names'}
                className="flex-1 rounded border bg-transparent px-2 py-1 text-xs"
                style={{ borderColor: 'var(--mars-color-border)', fontWeight: locked ? 600 : 400 }}
              />
              {locked && (
                <span className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
                  style={{ background: '#8b5cf622', color: '#a78bfa' }}>
                  Default
                </span>
              )}

              {/* Length buttons */}
              <div className="flex overflow-hidden rounded border" style={{ borderColor: 'var(--mars-color-border)' }}>
                {LENGTH_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    title={opt.hint}
                    onClick={() => setLength(i, opt)}
                    className="px-2 py-1 text-[10px] font-semibold transition-colors"
                    style={{
                      background: currentLength === opt.value ? opt.color : 'transparent',
                      color: currentLength === opt.value ? '#fff' : 'var(--mars-color-text-secondary)',
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* Custom word count — shown only when 'custom' is selected */}
              {currentLength === 'custom' && (
                <input
                  type="number"
                  min={50}
                  max={2000}
                  value={s.word_count ?? 400}
                  onChange={(e) => update(i, { word_count: e.target.value ? Number(e.target.value) : 400 })}
                  placeholder="words"
                  title="Target word count for this section"
                  className="w-16 rounded border bg-transparent px-1.5 py-1 text-[10px]"
                  style={{ borderColor: '#10b981' }}
                />
              )}

              <button onClick={() => remove(i)} disabled={locked} className="opacity-60 hover:opacity-100 disabled:opacity-20 disabled:cursor-not-allowed">
                <Trash2 className="h-4 w-4" style={{ color: locked ? 'var(--mars-color-text-tertiary)' : '#ef4444' }} />
              </button>
            </div>
            <input
              value={s.guidance ?? ''}
              onChange={(e) => update(i, { guidance: e.target.value })}
              placeholder="What should this section analyse / cover? (optional)"
              className="mt-1.5 w-full rounded border bg-transparent px-2 py-1 text-[11px]"
              style={{ borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text-secondary)' }}
            />
          </div>
          );
        })}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          onClick={add}
          className="flex items-center gap-1 rounded px-2 py-1 text-[11px]"
          style={{ color: 'var(--mars-color-text-secondary)' }}
        >
          <Plus className="h-3.5 w-3.5" /> Add blank section
        </button>
        <select
          value=""
          onChange={(e) => { addPredefined(e.target.value); e.currentTarget.selectedIndex = 0; }}
          className="rounded border bg-transparent px-2 py-1 text-[11px]"
          style={{ borderColor: 'var(--mars-color-border)', color: 'var(--mars-color-text-secondary)' }}
          title="Add one of the 22 standard sections"
        >
          <option value="">+ Add a standard section…</option>
          {CANONICAL_SECTION_NAMES.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
          Tone override (optional)
          <input value={tone} onChange={(e) => { setTone(e.target.value); setSaved(false); }}
            className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-[11px]"
            style={{ borderColor: 'var(--mars-color-border)' }} />
        </label>
        <label className="text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
          Audience override (optional)
          <input value={audience} onChange={(e) => { setAudience(e.target.value); setSaved(false); }}
            className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-[11px]"
            style={{ borderColor: 'var(--mars-color-border)' }} />
        </label>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <Button onClick={save} disabled={busy}>
          {saved ? 'Template saved ✓' : 'Save template'}
        </Button>
        {saved && (
          <span className="text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
            Now run Stage 4 to generate these sections.
          </span>
        )}
      </div>
    </Card>
  );
}
