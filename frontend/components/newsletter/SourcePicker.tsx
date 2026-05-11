'use client';

import { Globe, Link2, Search } from 'lucide-react';

import { Label, TextArea } from '@/components/core/Input';
import { SourceMode } from '@/types/newsletter';

interface Props {
  sourceMode: SourceMode;
  userUrls: string[];
  onSourceModeChange: (next: SourceMode) => void;
  onUserUrlsChange: (next: string[]) => void;
}

const options: {
  value: SourceMode;
  title: string;
  help: string;
  icon: typeof Link2;
  accent: string;
}[] = [
  { value: 'user_links_only', title: 'My links only', help: 'Validate and use only the URLs I provide.', icon: Link2, accent: '#06b6d4' },
  { value: 'ddgs_only', title: 'Web search only', help: 'Use the web-search agent (DDGS) — ignore my links.', icon: Search, accent: '#22c55e' },
  { value: 'combined', title: 'Combined', help: 'Use my links and the web-search agent. Deduplicate before curation.', icon: Globe, accent: '#8b5cf6' },
];

export function SourcePicker({ sourceMode, userUrls, onSourceModeChange, onUserUrlsChange }: Props) {
  return (
    <div className="space-y-3">
      <Label>Source mode</Label>
      <div className="grid gap-2 md:grid-cols-3">
        {options.map((opt) => {
          const active = sourceMode === opt.value;
          const Icon = opt.icon;
          return (
            <label
              key={opt.value}
              className="group cursor-pointer rounded-xl border p-3 transition-all duration-200 hover:-translate-y-0.5"
              style={{
                borderColor: active ? `${opt.accent}80` : 'var(--mars-color-border)',
                background: active
                  ? `linear-gradient(135deg, ${opt.accent}1f, ${opt.accent}08)`
                  : 'var(--mars-color-surface-overlay)',
                boxShadow: active ? `0 0 16px ${opt.accent}33` : 'none',
              }}
            >
              <input
                type="radio"
                className="sr-only"
                name="source_mode"
                value={opt.value}
                checked={active}
                onChange={() => onSourceModeChange(opt.value)}
              />
              <div className="flex items-center gap-2">
                <div
                  className="flex h-6 w-6 items-center justify-center rounded-md"
                  style={{
                    background: active ? `${opt.accent}33` : 'var(--mars-color-surface-sunken)',
                    border: `1px solid ${active ? `${opt.accent}55` : 'var(--mars-color-border)'}`,
                  }}
                >
                  <Icon className="h-3.5 w-3.5" style={{ color: active ? opt.accent : 'var(--mars-color-text-tertiary)' }} />
                </div>
                <div className="text-sm font-semibold" style={{ color: active ? opt.accent : 'var(--mars-color-text)' }}>
                  {opt.title}
                </div>
              </div>
              <div className="mt-1.5 text-[11px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                {opt.help}
              </div>
            </label>
          );
        })}
      </div>

      {sourceMode !== 'ddgs_only' && (
        <div>
          <Label hint="One URL per line, or comma-separated. Each will be checked for reachability + authority.">
            My URLs
          </Label>
          <TextArea
            rows={5}
            value={userUrls.join('\n')}
            onChange={(e) =>
              onUserUrlsChange(
                e.target.value
                  .split(/[\n,]/g)
                  .map((u) => u.trim())
                  .filter(Boolean),
              )
            }
            placeholder={'https://www.reuters.com/…\nhttps://www.fda.gov/…'}
          />
        </div>
      )}
    </div>
  );
}
