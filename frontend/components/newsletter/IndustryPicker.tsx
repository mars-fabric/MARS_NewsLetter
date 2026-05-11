'use client';

import { ChevronDown, Plus, Sparkles, Trash2, X } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/core/Button';
import { IndustryEntry, IndustrySelection } from '@/types/newsletter';

interface Props {
  taxonomy: IndustryEntry[];
  value: IndustrySelection[];
  onChange: (next: IndustrySelection[]) => void;
}

const CUSTOM_SENTINEL = '__custom__';

export function IndustryPicker({ taxonomy, value, onChange }: Props) {
  const [adding, setAdding] = useState(false);
  const [newIndustry, setNewIndustry] = useState<string>('');
  const [customName, setCustomName] = useState<string>('');

  const remainingIndustries = taxonomy.filter(
    (t) => !value.some((v) => v.industry === t.industry),
  );

  function resetAdd() {
    setNewIndustry('');
    setCustomName('');
    setAdding(false);
  }

  function add() {
    if (newIndustry === CUSTOM_SENTINEL) {
      const name = customName.trim();
      if (!name) return;
      if (value.some((v) => v.industry.toLowerCase() === name.toLowerCase())) return;
      onChange([...value, { industry: name, sub_domains: [] }]);
      resetAdd();
      return;
    }
    if (!newIndustry) return;
    const entry = taxonomy.find((t) => t.industry === newIndustry);
    if (!entry) return;
    onChange([...value, { industry: entry.industry, sub_domains: [] }]);
    resetAdd();
  }

  function removeAt(idx: number) {
    onChange(value.filter((_, i) => i !== idx));
  }

  function toggleSub(idx: number, sub: string) {
    const sel = value[idx];
    const next = sel.sub_domains.includes(sub)
      ? sel.sub_domains.filter((s) => s !== sub)
      : [...sel.sub_domains, sub];
    onChange(value.map((v, i) => (i === idx ? { ...v, sub_domains: next } : v)));
  }

  function addCustomSub(idx: number, raw: string) {
    const cleaned = raw
      .split(/[,\n]/g)
      .map((s) => s.trim())
      .filter(Boolean);
    if (cleaned.length === 0) return;
    const sel = value[idx];
    const merged = Array.from(new Set([...sel.sub_domains, ...cleaned]));
    onChange(value.map((v, i) => (i === idx ? { ...v, sub_domains: merged } : v)));
  }

  function removeSub(idx: number, sub: string) {
    const sel = value[idx];
    onChange(
      value.map((v, i) =>
        i === idx ? { ...v, sub_domains: v.sub_domains.filter((s) => s !== sub) } : v,
      ),
    );
  }

  const customSelected = newIndustry === CUSTOM_SENTINEL;
  const canConfirmAdd = customSelected ? customName.trim().length > 0 : !!newIndustry;

  return (
    <div className="space-y-3">
      {!adding && (
        <div className="flex justify-end">
          <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
            <Plus size={12} /> Add industry
          </Button>
        </div>
      )}

      {adding && (
        <div
          className="space-y-2 rounded-xl p-3"
          style={{
            border: '1px solid var(--mars-color-border)',
            background: 'var(--mars-color-surface-sunken)',
          }}
        >
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <select
                className="mars-select w-full rounded-lg px-3 py-2 pr-8 text-sm"
                value={newIndustry}
                onChange={(e) => setNewIndustry(e.target.value)}
              >
                <option value="">Choose an industry…</option>
                <option value={CUSTOM_SENTINEL}>✨ Custom industry (enter your own)</option>
                {remainingIndustries.length > 0 && <option disabled>──────────</option>}
                {remainingIndustries.map((t) => (
                  <option key={t.industry} value={t.industry}>
                    {t.industry} — {t.industry_domain}
                  </option>
                ))}
              </select>
              <ChevronDown
                className="pointer-events-none absolute right-2 top-2.5"
                size={16}
                style={{ color: 'var(--mars-color-text-tertiary)' }}
              />
            </div>
            <Button onClick={add} disabled={!canConfirmAdd}>
              Add
            </Button>
            <Button variant="ghost" onClick={resetAdd}>
              Cancel
            </Button>
          </div>

          {customSelected && (
            <div
              className="mars-anim-slide-up rounded-lg p-2.5"
              style={{
                background: 'var(--mars-color-surface)',
                border: '1px dashed rgba(139,92,246,0.4)',
              }}
            >
              <div
                className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider"
                style={{ color: 'var(--mars-color-primary, #8b5cf6)' }}
              >
                <Sparkles className="h-3 w-3" />
                Custom industry name
              </div>
              <input
                type="text"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    add();
                  }
                }}
                placeholder="e.g. Quantum Computing, Climate Tech, Supply Chain…"
                autoFocus
                className="w-full rounded-md border px-2.5 py-1.5 text-sm outline-none transition-colors focus:border-[var(--mars-color-primary,#8b5cf6)]"
                style={{
                  background: 'var(--mars-color-surface-overlay)',
                  borderColor: 'var(--mars-color-border)',
                  color: 'var(--mars-color-text)',
                }}
              />
              <p className="mt-1.5 text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                You'll be able to add your own sub-domains in the next step.
              </p>
            </div>
          )}
        </div>
      )}

      {value.length === 0 && !adding && (
        <p
          className="rounded-lg border border-dashed p-6 text-center text-xs"
          style={{
            borderColor: 'var(--mars-color-border)',
            background: 'var(--mars-color-surface-sunken)',
            color: 'var(--mars-color-text-tertiary)',
          }}
        >
          No industries selected yet. Click <strong style={{ color: 'var(--mars-color-text-secondary)' }}>Add industry</strong> to start — pick from the catalogue or add your own.
        </p>
      )}

      <ul className="space-y-2">
        {value.map((sel, idx) => {
          const entry = taxonomy.find((t) => t.industry === sel.industry);
          const isCustom = !entry;
          return (
            <li
              key={sel.industry}
              className="rounded-xl p-3 transition-all duration-200"
              style={{
                background: 'var(--mars-color-surface-overlay)',
                border: isCustom
                  ? '1px dashed rgba(139,92,246,0.45)'
                  : '1px solid var(--mars-color-border)',
                boxShadow: isCustom
                  ? 'inset 0 1px 0 rgba(255,255,255,0.03), 0 0 12px rgba(139,92,246,0.10)'
                  : 'inset 0 1px 0 rgba(255,255,255,0.03)',
              }}
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {isCustom && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider"
                      style={{
                        background: 'rgba(139,92,246,0.18)',
                        color: 'var(--mars-color-primary, #8b5cf6)',
                        border: '1px solid rgba(139,92,246,0.35)',
                      }}
                    >
                      <Sparkles className="h-2.5 w-2.5" />
                      Custom
                    </span>
                  )}
                  <div>
                    <div className="text-sm font-semibold" style={{ color: 'var(--mars-color-text)' }}>
                      {sel.industry}
                    </div>
                    <div className="text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                      {entry?.industry_domain ?? 'Custom industry — define your own sub-domains'}
                    </div>
                  </div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => removeAt(idx)} aria-label="Remove">
                  <Trash2 size={13} />
                </Button>
              </div>

              {isCustom ? (
                <CustomSubDomainEditor
                  selected={sel.sub_domains}
                  onAdd={(raw) => addCustomSub(idx, raw)}
                  onRemove={(sub) => removeSub(idx, sub)}
                />
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {entry!.sub_domains.map((sub) => {
                    const active = sel.sub_domains.includes(sub);
                    return (
                      <button
                        key={sub}
                        type="button"
                        onClick={() => toggleSub(idx, sub)}
                        className={`mars-pill rounded-full px-3 py-1 text-[11px] font-medium ${active ? 'is-active' : ''}`}
                      >
                        {sub}
                      </button>
                    );
                  })}
                </div>
              )}

              {sel.sub_domains.length === 0 && (
                <p className="mt-2 text-[11px]" style={{ color: 'var(--mars-color-warning)' }}>
                  {isCustom ? 'Add at least one sub-domain.' : 'Pick at least one sub-domain.'}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CustomSubDomainEditor({
  selected,
  onAdd,
  onRemove,
}: {
  selected: string[];
  onAdd: (raw: string) => void;
  onRemove: (sub: string) => void;
}) {
  const [draft, setDraft] = useState('');

  function commit() {
    if (!draft.trim()) return;
    onAdd(draft);
    setDraft('');
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {selected.map((sub) => (
          <span
            key={sub}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium"
            style={{
              background: 'rgba(139,92,246,0.15)',
              color: 'var(--mars-color-primary, #8b5cf6)',
              border: '1px solid rgba(139,92,246,0.35)',
            }}
          >
            {sub}
            <button
              type="button"
              onClick={() => onRemove(sub)}
              className="rounded-full p-0.5 transition-colors hover:bg-red-500/25"
              aria-label={`Remove ${sub}`}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault();
              commit();
            }
          }}
          placeholder="Type a sub-domain and press Enter…"
          className="flex-1 rounded-md border px-2.5 py-1.5 text-[12px] outline-none transition-colors focus:border-[var(--mars-color-primary,#8b5cf6)]"
          style={{
            background: 'var(--mars-color-surface)',
            borderColor: 'var(--mars-color-border)',
            color: 'var(--mars-color-text)',
          }}
        />
        <Button size="sm" variant="secondary" onClick={commit} disabled={!draft.trim()}>
          <Plus size={12} /> Add
        </Button>
      </div>
      <p className="text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
        Tip: separate multiple sub-domains with commas to add several at once.
      </p>
    </div>
  );
}
