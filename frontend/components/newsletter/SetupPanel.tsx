'use client';

import { AlertTriangle, CalendarDays, Check, FileText, Layers, Rocket, Settings2, Users } from 'lucide-react';
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/core/Button';
import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';
import { useTaxonomy } from '@/hooks/useTaxonomy';
import { daysAgo, todayIso } from '@/lib/dateUtils';
import {
  IndustrySelection,
  NewsletterCreateRequest,
  SourceMode,
  StageModeConfig,
} from '@/types/newsletter';

import { IndustryPicker } from './IndustryPicker';
import { SourcePicker } from './SourcePicker';
import { StageAdvancedSettings } from './StageAdvancedSettings';

interface Props {
  onCreate: (req: NewsletterCreateRequest) => Promise<string | null>;
  busy?: boolean;
}

const DEFAULT_MODE_CONFIG: StageModeConfig = {
  // planning_and_control is the PaperPulse-style planner→researcher→engineer
  // pipeline; one_shot is a single researcher agent. Defaults: P&C for the
  // discovery-heavy stages (2 source-collection, 3 curation), one_shot for
  // the generation/review stages where Stage 4's own section orchestrator
  // and Stage 5's LangGraph handle planning themselves.
  stage_2_mode: 'planning_and_control',
  stage_3_mode: 'planning_and_control',
  stage_4_mode: 'one_shot',
  stage_5_mode: 'one_shot',
  // Stage-2 collection knobs
  stage_2_top_companies_count: 12,
  stage_2_min_sources: 30,
  stage_2_enrich_with_llm: true,
  stage_2_models: {},
  stage_3_models: {},
  stage_4_models: {},
  stage_5_models: {},
  stage_2_limits: {},
  stage_3_limits: {},
  stage_4_limits: {},
  stage_5_limits: {},
};

const SECTION_META: { id: string; num: number; title: string; icon: typeof FileText }[] = [
  { id: 'sec-scope', num: 1, title: 'Scope', icon: FileText },
  { id: 'sec-industries', num: 2, title: 'Industries', icon: Layers },
  { id: 'sec-sources', num: 3, title: 'Sources', icon: Users },
  { id: 'sec-strategy', num: 4, title: 'Agent strategy', icon: Settings2 },
];

export function SetupPanel({ onCreate, busy }: Props) {
  const { data, loading, error } = useTaxonomy();

  const today = todayIso();
  const [title, setTitle] = useState('');
  const [audience, setAudience] = useState('');
  const [dateFrom, setDateFrom] = useState(daysAgo(7));
  const [dateTo, setDateTo] = useState(today);
  const [industries, setIndustries] = useState<IndustrySelection[]>([]);
  const [sourceMode, setSourceMode] = useState<SourceMode>('combined');
  const [userUrls, setUserUrls] = useState<string[]>([]);
  const [modeConfig, setModeConfig] = useState<StageModeConfig>(DEFAULT_MODE_CONFIG);

  const [activeSection, setActiveSection] = useState<string>('sec-scope');
  const containerRef = useRef<HTMLDivElement>(null);

  /** Scroll-spy: highlight the step that's currently in view. */
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) setActiveSection(visible.target.id);
      },
      { rootMargin: '-25% 0px -55% 0px', threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    SECTION_META.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);

  /** Per-section completion — drives the green tick on each rail item. */
  const completion: Record<string, boolean> = useMemo(() => ({
    'sec-scope': dateFrom <= dateTo && dateTo <= today,
    'sec-industries': industries.length > 0 && industries.every((i) => i.sub_domains.length > 0),
    'sec-sources': sourceMode === 'ddgs_only' || userUrls.length > 0,
    'sec-strategy': true,
  }), [dateFrom, dateTo, today, industries, sourceMode, userUrls]);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // Auto-derive a sensible title from the industries + coverage window so the
  // user doesn't have to type one. If they leave the title field blank we pass
  // this string to the backend instead of `null`, which keeps the session
  // sidebar from showing an awkward "Untitled Newsletter" placeholder.
  const autoTitle = useMemo(() => {
    const inds = industries
      .map((i) => i.industry)
      .filter(Boolean)
      .slice(0, 3);
    const left = inds.length === 0
      ? 'Newsletter'
      : inds.length <= 2
        ? inds.join(' · ')
        : `${inds.slice(0, 2).join(' · ')} +${industries.length - 2}`;
    const right = dateFrom && dateTo ? `${dateFrom} → ${dateTo}` : '';
    return right ? `${left} · ${right}` : left;
  }, [industries, dateFrom, dateTo]);

  const effectiveTitle = title.trim() || autoTitle;

  const validation = useMemo(() => {
    const errs: string[] = [];
    if (!industries.length) errs.push('Pick at least one industry.');
    industries.forEach((i) => {
      if (!i.sub_domains.length) errs.push(`Pick at least one sub-domain for ${i.industry}.`);
    });
    if (dateFrom > dateTo) errs.push('Start date must be on or before end date.');
    if (dateTo > today) errs.push('Coverage end cannot be in the future.');
    if (sourceMode !== 'ddgs_only' && userUrls.length === 0)
      errs.push('Provide at least one URL or switch to "Web search only".');
    return errs;
  }, [industries, dateFrom, dateTo, today, sourceMode, userUrls]);

  const canSubmit = validation.length === 0 && !busy;

  async function submit() {
    const req: NewsletterCreateRequest = {
      title: effectiveTitle,
      industries,
      date_from: dateFrom,
      date_to: dateTo,
      source_mode: sourceMode,
      user_urls: userUrls,
      audience: audience.trim() || null,
      mode_config: modeConfig,
    };
    await onCreate(req);
  }

  if (loading) {
    return (
      <Card>
        <CardTitle>Loading taxonomy…</CardTitle>
      </Card>
    );
  }
  if (error || !data) {
    return (
      <Card>
        <CardTitle>Failed to load taxonomy</CardTitle>
        <CardSubtitle>{error ?? 'Unknown error'}</CardSubtitle>
      </Card>
    );
  }

  return (
    <div ref={containerRef} className="mars-anim-fade-in grid gap-6 lg:grid-cols-[200px_minmax(0,1fr)]">
      {/* Sticky step rail — fills the previously-empty left margin */}
      <aside className="hidden lg:block">
        <div
          className="sticky top-4 space-y-1 rounded-2xl p-3"
          style={{
            border: '1px solid rgba(255,255,255,0.08)',
            background: 'linear-gradient(180deg, rgba(31,41,55,0.55), rgba(17,24,39,0.55))',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 16px -8px rgba(0,0,0,0.4)',
          }}
        >
          <p
            className="px-2.5 pb-2 pt-1 text-[10px] font-bold uppercase tracking-[0.12em]"
            style={{ color: 'var(--mars-color-text-tertiary)' }}
          >
            Setup steps
          </p>
          {SECTION_META.map((s) => {
            const isActive = activeSection === s.id;
            const isDone = completion[s.id];
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => scrollTo(s.id)}
                className="group relative flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-all duration-200"
                style={{
                  background: isActive
                    ? 'linear-gradient(135deg, rgba(139,92,246,0.20), rgba(99,102,241,0.08))'
                    : 'transparent',
                  border: isActive ? '1px solid rgba(139,92,246,0.40)' : '1px solid transparent',
                  boxShadow: isActive ? '0 0 14px rgba(139,92,246,0.18)' : 'none',
                }}
              >
                {isActive && (
                  <span
                    aria-hidden
                    className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r-full"
                    style={{
                      background: 'linear-gradient(180deg, #8b5cf6, #6366f1)',
                      boxShadow: '0 0 8px rgba(139,92,246,0.7)',
                    }}
                  />
                )}
                <span
                  className="relative flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-lg text-[10px] font-bold"
                  style={{
                    background: isDone
                      ? 'linear-gradient(135deg, #22c55e, #16a34a)'
                      : isActive
                        ? 'linear-gradient(135deg, #8b5cf6, #6366f1)'
                        : 'var(--mars-color-surface-overlay)',
                    color: isDone || isActive ? '#fff' : 'var(--mars-color-text-tertiary)',
                    boxShadow: isDone
                      ? '0 0 10px rgba(34,197,94,0.45)'
                      : isActive
                        ? '0 0 10px rgba(139,92,246,0.45)'
                        : 'none',
                  }}
                >
                  {isDone ? <Check className="h-3 w-3" strokeWidth={3} /> : s.num}
                </span>
                <span
                  className="flex flex-col text-[11.5px] leading-tight"
                  style={{
                    color: isActive
                      ? 'var(--mars-color-text)'
                      : isDone
                        ? 'var(--mars-color-text-secondary)'
                        : 'var(--mars-color-text-tertiary)',
                  }}
                >
                  <span className="font-semibold">{s.title}</span>
                  <span className="mt-0.5 text-[9.5px] uppercase tracking-wider opacity-60">
                    Step {s.num}
                  </span>
                </span>
                <s.icon
                  className="ml-auto h-3 w-3 flex-shrink-0 transition-opacity"
                  style={{
                    color: isActive ? 'var(--mars-color-primary)' : 'var(--mars-color-text-tertiary)',
                    opacity: isActive ? 1 : 0.5,
                  }}
                />
              </button>
            );
          })}

          {/* Mini progress meter at the bottom of the rail */}
          <div className="mt-3 px-2.5 pt-3" style={{ borderTop: '1px solid var(--mars-color-border)' }}>
            <div className="flex items-baseline justify-between text-[10px]">
              <span className="font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                Ready
              </span>
              <span className="tabular-nums font-bold" style={{ color: 'var(--mars-color-text)' }}>
                {Object.values(completion).filter(Boolean).length}/{SECTION_META.length}
              </span>
            </div>
            <div
              className="mt-1.5 h-1 overflow-hidden rounded-full"
              style={{ background: 'var(--mars-color-surface-overlay)' }}
            >
              <div
                className="h-full transition-all duration-500"
                style={{
                  width: `${(Object.values(completion).filter(Boolean).length / SECTION_META.length) * 100}%`,
                  background: 'linear-gradient(90deg, #8b5cf6, #22c55e)',
                  boxShadow: '0 0 8px rgba(139,92,246,0.5)',
                }}
              />
            </div>
          </div>
        </div>
      </aside>

      {/* Form column */}
      <div className="space-y-7">
      {/* Section 1 — Newsletter scope */}
      <Section
        id="sec-scope"
        num={1}
        title="Newsletter scope"
        hint="Title, audience, and the date window the newsletter should cover."
      >
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <Field icon={<FileText size={14} />} label="Newsletter title" optional>
              <input
                type="text"
                placeholder={autoTitle}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Field>
            {!title.trim() && (
              <p
                className="mt-1.5 flex items-center gap-1.5 text-[10px] leading-snug"
                style={{ color: 'var(--mars-color-text-tertiary)' }}
              >
                <span
                  className="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
                  style={{
                    background: 'var(--mars-color-primary-subtle, rgba(139,92,246,0.18))',
                    color: 'var(--mars-color-primary, #8b5cf6)',
                  }}
                >
                  Auto
                </span>
                <span className="truncate">
                  Will use <span style={{ color: 'var(--mars-color-text-secondary)' }}>{autoTitle}</span>
                </span>
              </p>
            )}
          </div>
          <Field icon={<Users size={14} />} label="Audience" optional>
            <input
              type="text"
              placeholder="e.g. CISOs at mid-market manufacturers"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
            />
          </Field>
          <Field icon={<CalendarDays size={14} />} label="Coverage start">
            <input
              type="date"
              value={dateFrom}
              max={dateTo || today}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </Field>
          <Field icon={<CalendarDays size={14} />} label="Coverage end">
            <input
              type="date"
              value={dateTo}
              max={today}
              min={dateFrom}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </Field>
        </div>
      </Section>

      {/* Section 2 — Industries & sub-domains */}
      <Section
        id="sec-industries"
        num={2}
        title="Industries & sub-domains"
        hint="Each industry can be filtered to specific sub-domains."
      >
        <IndustryPicker taxonomy={data.industries} value={industries} onChange={setIndustries} />
      </Section>

      {/* Section 3 — Sources */}
      <Section id="sec-sources" num={3} title="Sources" hint="Choose where the model fetches material from.">
        <SourcePicker
          sourceMode={sourceMode}
          userUrls={userUrls}
          onSourceModeChange={setSourceMode}
          onUserUrlsChange={setUserUrls}
        />
      </Section>

      {/* Section 4 — Per-stage agent strategy (cmbagent mode + model overrides) */}
      <Section
        id="sec-strategy"
        num={4}
        title="Per-stage agent strategy"
        hint="Override the cmbagent invocation mode and per-role model for each AI stage."
      >
        <StageAdvancedSettings value={modeConfig} onChange={setModeConfig} />
      </Section>

      {validation.length > 0 && (
        <div
          className="mars-anim-slide-up rounded-xl border p-4"
          style={{
            borderColor: 'rgba(245, 158, 11, 0.45)',
            background: 'linear-gradient(135deg, rgba(245,158,11,0.10), rgba(245,158,11,0.02))',
          }}
        >
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" style={{ color: 'var(--mars-color-warning)' }} />
            <div>
              <p className="text-sm font-semibold" style={{ color: '#fde68a' }}>
                Almost ready — fix these first
              </p>
              <ul className="mt-1.5 list-disc pl-5 text-[11px] leading-relaxed" style={{ color: 'var(--mars-color-text-secondary)' }}>
                {validation.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <Button size="lg" onClick={submit} disabled={!canSubmit} loading={busy}>
          <Rocket size={16} />
          Create newsletter run
          <span className="opacity-70">→</span>
        </Button>
      </div>
      </div>
    </div>
  );
}

// ─── Local UI primitives ──────────────────────────────────────────────────

function Section({
  id,
  num,
  title,
  hint,
  action,
  children,
}: {
  id?: string;
  num: number;
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className="mars-section-card mars-anim-slide-up p-5 scroll-mt-4"
      style={{ animationDelay: `${num * 60}ms` }}
    >
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-baseline gap-2.5">
          <span className="mars-step-num">{num}</span>
          <div>
            <h3 className="text-sm font-semibold leading-tight" style={{ color: 'var(--mars-color-text)' }}>
              {title}
            </h3>
            {hint && (
              <p className="mt-0.5 text-[11px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                {hint}
              </p>
            )}
          </div>
        </div>
        {action && <div className="flex-shrink-0">{action}</div>}
      </header>
      {children}
    </section>
  );
}

function Field({
  icon,
  label,
  optional,
  children,
}: {
  icon: ReactNode;
  label: string;
  optional?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span
        className="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.08em]"
        style={{ color: 'var(--mars-color-text-tertiary)' }}
      >
        <span style={{ color: 'var(--mars-color-text-secondary)' }}>{icon}</span>
        {label}
        {optional && (
          <span
            className="ml-1 rounded-full px-1.5 py-0.5 text-[9px] font-medium normal-case tracking-normal"
            style={{
              background: 'var(--mars-color-surface-overlay)',
              color: 'var(--mars-color-text-tertiary)',
            }}
          >
            optional
          </span>
        )}
      </span>
      <div className="mars-field mars-field--with-icon relative">
        <span className="mars-field-icon">{icon}</span>
        {children}
      </div>
    </label>
  );
}
