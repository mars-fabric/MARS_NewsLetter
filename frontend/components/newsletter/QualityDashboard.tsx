'use client';

/**
 * QualityDashboard — renders the Stage-5 LangGraph quality dashboard.
 *
 * Fetches /api/newsletter/{task_id}/dashboard and visualises:
 *   - Overall authenticity score (radial gauge)
 *   - Sub-score breakdown (horizontal bars)
 *   - URL verification (reachable / dead donut + dead-link list)
 *   - Source-mix top-10 domains (bar chart)
 *   - Critic corrections + DDGS findings (tables)
 *   - Weak sections list
 *
 * Charts are pure SVG to avoid adding a new dependency. The dashboard endpoint
 * already returns viz-ready arrays so the component is mostly presentation.
 */

import { AlertTriangle, CheckCircle2, FileText, Link2, ShieldCheck, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Card, CardSubtitle, CardTitle } from '@/components/core/Card';

interface DashboardPayload {
  task_id: string;
  stage_5_status: string | null;
  score_card: {
    authenticity_score?: number;
    verdict?: string;
    citation_score?: number;
    factual_fidelity_score?: number;
    coverage_score?: number;
    structural_completeness_score?: number;
    suggestions?: string[];
    notes?: string;
  };
  aggregate: {
    overall_score?: number;
    scores?: Record<string, number>;
    weights?: Record<string, number>;
    redundancy_penalty?: number;
  };
  dashboard: {
    gauges?: { key: string; label: string; value: number }[];
    donut_source_mix?: { domain: string; count: number }[];
    bar_category_mix?: { category: string; count: number }[];
    kpis?: Record<string, number>;
    weak_sections_table?: { section: string; issue: string; severity: string }[];
    user_url_coverage?: {
      expected_user_urls?: number;
      cited_user_urls?: number;
      missing_user_urls?: string[];
      coverage_pct?: number;
    };
    pdf_backend?: string | null;
    pdf_error?: string | null;
    pdf_path?: string | null;
  };
  url_verification: {
    total?: number;
    reachable?: number;
    dead?: number;
    reachability_pct?: number;
    results?: { url: string; reachable: boolean; status_code: number | null; domain?: string }[];
  };
  critic: {
    corrections?: { section: string; issue: string; severity: string; recommendation: string }[];
    tone_pass?: boolean;
    tone_notes?: string;
    ddgs_findings?: { section: string; issue: string; candidates: { title: string; url: string }[] }[];
  };
  verification_notes: string[];
  node_timings: Record<string, number>;
}

interface Props {
  taskId: string;
  accent: string;
}

export function QualityDashboard({ taskId, accent }: Props) {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`/api/newsletter/${encodeURIComponent(taskId)}/dashboard`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((json) => {
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  if (loading) {
    return (
      <Card>
        <CardTitle>Quality dashboard</CardTitle>
        <CardSubtitle>Loading…</CardSubtitle>
      </Card>
    );
  }
  if (error || !data) {
    return (
      <Card>
        <CardTitle>Quality dashboard</CardTitle>
        <CardSubtitle>Could not load dashboard: {error || 'no data'}</CardSubtitle>
      </Card>
    );
  }

  const overall = Math.round(data.aggregate?.overall_score ?? 0);
  const verdict = data.score_card?.verdict || 'n/a';
  const verdictColor =
    verdict === 'production-ready' ? '#10b981' : verdict === 'needs-revision' ? '#f59e0b' : '#ef4444';

  const subScores = Object.entries(data.aggregate?.scores || {}).map(([k, v]) => ({
    key: k,
    label: k.charAt(0).toUpperCase() + k.slice(1),
    value: Number(v) || 0,
  }));

  const verif = data.url_verification || {};
  const totalUrls = verif.total ?? 0;
  const reachable = verif.reachable ?? 0;
  const reachPct = verif.reachability_pct ?? 0;
  const deadUrls = (verif.results || []).filter((r) => !r.reachable).slice(0, 8);

  const sourceMix = (data.dashboard?.donut_source_mix || []).slice(0, 10);
  const maxSource = Math.max(1, ...sourceMix.map((s) => s.count));

  const corrections = data.critic?.corrections || [];
  const ddgs = data.critic?.ddgs_findings || [];
  const weakSections = data.dashboard?.weak_sections_table || [];
  const kpis = data.dashboard?.kpis || {};
  const userCoverage = data.dashboard?.user_url_coverage || {};
  const pdfBackend = data.dashboard?.pdf_backend || null;
  const pdfError = data.dashboard?.pdf_error || null;

  return (
    <div className="space-y-4">
      {/* Header: overall score + verdict */}
      <Card accent={accent} style={{ borderColor: `${accent}33` }}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <CardTitle>Quality dashboard</CardTitle>
            <CardSubtitle>
              Authenticity, citation health, structural coverage & critic findings — produced by the
              Stage-5 LangGraph pipeline.
            </CardSubtitle>
          </div>
          <div className="flex items-center gap-4">
            <Gauge value={overall} accent={accent} />
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                Verdict
              </div>
              <div className="text-lg font-bold" style={{ color: verdictColor }}>
                {verdict}
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* Sub-scores + KPIs */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Sub-scores</CardTitle>
          <CardSubtitle>How the overall authenticity score breaks down.</CardSubtitle>
          <div className="mt-3 space-y-2">
            {subScores.map((s) => (
              <BarRow key={s.key} label={s.label} value={s.value} max={100} accent={accent} suffix="/100" />
            ))}
            {data.aggregate?.redundancy_penalty ? (
              <div className="mt-2 text-[11px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                Redundancy penalty applied: −{data.aggregate.redundancy_penalty}
              </div>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardTitle>Key figures</CardTitle>
          <CardSubtitle>What was processed in this run.</CardSubtitle>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
            <Kpi label="Curated items" value={kpis.items} icon={<FileText size={14} />} />
            <Kpi label="Unique domains" value={kpis.unique_domains} icon={<Link2 size={14} />} />
            <Kpi label="Sections" value={kpis.sections} icon={<ShieldCheck size={14} />} />
            <Kpi label="Non-empty sections" value={kpis.non_empty_sections} icon={<CheckCircle2 size={14} />} />
            <Kpi label="Top items" value={kpis.top_items} />
            <Kpi label="Uncited items" value={kpis.uncited_items} icon={<AlertTriangle size={14} />} />
            <Kpi label="Duplicate URL groups" value={kpis.duplicate_groups} />
            <Kpi label="URLs verified" value={totalUrls} />
          </div>
        </Card>
      </div>

      {/* URL verification + source mix */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>URL verification</CardTitle>
              <CardSubtitle>HEAD-checks against every cited URL.</CardSubtitle>
            </div>
            <Donut reachable={reachable} dead={totalUrls - reachable} />
          </div>
          <div className="mt-3 text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
            <span style={{ color: '#10b981', fontWeight: 600 }}>{reachable}</span> reachable ·{' '}
            <span style={{ color: '#ef4444', fontWeight: 600 }}>{totalUrls - reachable}</span> dead ·{' '}
            {reachPct}% healthy
          </div>
          {deadUrls.length > 0 && (
            <div className="mt-3 space-y-1.5 max-h-44 overflow-auto pr-2">
              <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                Dead / inaccessible URLs
              </div>
              {deadUrls.map((r, i) => (
                <div key={i} className="text-[11px] truncate" style={{ color: 'var(--mars-color-text-secondary)' }}>
                  <XCircle size={11} className="inline mr-1" style={{ color: '#ef4444' }} />
                  <code className="text-[10px]">{r.status_code ?? '—'}</code>{' '}
                  <a href={r.url} target="_blank" rel="noreferrer" style={{ color: accent }}>
                    {r.url}
                  </a>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>Top source domains</CardTitle>
          <CardSubtitle>Citation concentration across the newsletter.</CardSubtitle>
          <div className="mt-3 space-y-1.5">
            {sourceMix.length === 0 ? (
              <div className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>No source data.</div>
            ) : (
              sourceMix.map((s) => (
                <BarRow key={s.domain} label={s.domain} value={s.count} max={maxSource} accent={accent} suffix="" />
              ))
            )}
          </div>
        </Card>
      </div>

      {/* User-URL coverage + PDF backend */}
      {((userCoverage.expected_user_urls ?? 0) > 0 || pdfBackend || pdfError) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {(userCoverage.expected_user_urls ?? 0) > 0 && (
            <Card>
              <CardTitle>User-provided links</CardTitle>
              <CardSubtitle>
                Did the writer cite every URL you supplied (and that survived the relevance gate)?
              </CardSubtitle>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="text-2xl font-bold tabular-nums" style={{ color: accent }}>
                  {userCoverage.cited_user_urls ?? 0}
                </span>
                <span className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                  / {userCoverage.expected_user_urls} cited ({userCoverage.coverage_pct ?? 0}%)
                </span>
              </div>
              {(userCoverage.missing_user_urls || []).length > 0 && (
                <div className="mt-3 space-y-1 max-h-32 overflow-auto pr-2">
                  <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                    Not cited yet
                  </div>
                  {(userCoverage.missing_user_urls || []).slice(0, 8).map((u, i) => (
                    <div key={i} className="text-[11px] truncate" style={{ color: 'var(--mars-color-text-secondary)' }}>
                      <AlertTriangle size={11} className="inline mr-1" style={{ color: '#f59e0b' }} />
                      <a href={u} target="_blank" rel="noreferrer" style={{ color: accent }}>{u}</a>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}
          {(pdfBackend || pdfError) && (
            <Card>
              <CardTitle>PDF rendering</CardTitle>
              <CardSubtitle>Which backend produced the downloadable PDF.</CardSubtitle>
              <div className="mt-3 text-xs" style={{ color: 'var(--mars-color-text-secondary)' }}>
                <span className="font-mono" style={{ color: pdfError ? '#ef4444' : '#10b981' }}>
                  {pdfBackend || 'unavailable'}
                </span>
                {pdfBackend === 'fpdf2' && (
                  <span className="ml-2 text-[11px]" style={{ color: '#f59e0b' }}>
                    (WeasyPrint unavailable — using fpdf2 fallback)
                  </span>
                )}
                {pdfError && (
                  <div className="mt-2 rounded border px-2 py-1.5 text-[11px]"
                    style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.06)', color: '#fca5a5' }}>
                    {pdfError}
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Critic corrections + DDGS findings */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Critic corrections</CardTitle>
          <CardSubtitle>
            LLM critic findings against the curated ground truth.{' '}
            {data.critic?.tone_pass != null && (
              <span style={{ color: data.critic.tone_pass ? '#10b981' : '#f59e0b' }}>
                Tone: {data.critic.tone_pass ? 'pass' : 'fail'}
              </span>
            )}
          </CardSubtitle>
          <div className="mt-3 space-y-2 max-h-72 overflow-auto pr-2">
            {corrections.length === 0 ? (
              <div className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                No corrections — critic gave a clean pass.
              </div>
            ) : (
              corrections.map((c, i) => (
                <div
                  key={i}
                  className="rounded border p-2 text-[11px]"
                  style={{
                    borderColor: 'var(--mars-color-border)',
                    background: 'var(--mars-color-surface-sunken)',
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold" style={{ color: 'var(--mars-color-text-primary)' }}>
                      {c.section || '(no section)'}
                    </span>
                    <SeverityBadge severity={c.severity} />
                  </div>
                  <div className="mt-1" style={{ color: 'var(--mars-color-text-secondary)' }}>
                    {c.issue}
                  </div>
                  {c.recommendation && (
                    <div className="mt-1 italic" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                      → {c.recommendation}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardTitle>Weak sections</CardTitle>
          <CardSubtitle>Canonical sections missing or under-substantive.</CardSubtitle>
          <div className="mt-3 space-y-1.5 max-h-72 overflow-auto pr-2">
            {weakSections.length === 0 ? (
              <div className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                All sections substantive.
              </div>
            ) : (
              weakSections.map((w, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded border px-2 py-1.5 text-[11px]"
                  style={{
                    borderColor: 'var(--mars-color-border)',
                    background: 'var(--mars-color-surface-sunken)',
                  }}
                >
                  <div>
                    <div className="font-semibold" style={{ color: 'var(--mars-color-text-primary)' }}>
                      {w.section}
                    </div>
                    <div style={{ color: 'var(--mars-color-text-tertiary)' }}>{w.issue}</div>
                  </div>
                  <SeverityBadge severity={w.severity} />
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* DDGS findings + suggestions */}
      {(ddgs.length > 0 || (data.score_card?.suggestions || []).length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardTitle>Live web research</CardTitle>
            <CardSubtitle>DDGS searches run against high-severity critic findings.</CardSubtitle>
            <div className="mt-3 space-y-2 max-h-64 overflow-auto pr-2">
              {ddgs.length === 0 ? (
                <div className="text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                  No DDGS research triggered (no high-severity findings).
                </div>
              ) : (
                ddgs.map((f, i) => (
                  <div
                    key={i}
                    className="rounded border p-2 text-[11px]"
                    style={{
                      borderColor: 'var(--mars-color-border)',
                      background: 'var(--mars-color-surface-sunken)',
                    }}
                  >
                    <div className="font-semibold" style={{ color: 'var(--mars-color-text-primary)' }}>
                      {f.section}
                    </div>
                    <div className="mt-1" style={{ color: 'var(--mars-color-text-secondary)' }}>
                      {f.issue}
                    </div>
                    {(f.candidates || []).slice(0, 3).map((h, j) => (
                      <a
                        key={j}
                        href={h.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 block truncate"
                        style={{ color: accent }}
                      >
                        → {h.title}
                      </a>
                    ))}
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>Suggestions</CardTitle>
            <CardSubtitle>Actionable next steps to lift quality.</CardSubtitle>
            <ul className="mt-3 space-y-1.5 text-[11px]" style={{ color: 'var(--mars-color-text-secondary)' }}>
              {(data.score_card?.suggestions || []).map((s, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <span style={{ color: accent }}>›</span>
                  <span>{s}</span>
                </li>
              ))}
              {!(data.score_card?.suggestions || []).length && (
                <li style={{ color: 'var(--mars-color-text-tertiary)' }}>No suggestions.</li>
              )}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

// ── primitives ──────────────────────────────────────────────────────────────

function Gauge({ value, accent }: { value: number; accent: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - clamped / 100);
  return (
    <svg width="96" height="96" viewBox="0 0 96 96">
      <circle cx="48" cy="48" r={r} fill="none" stroke="var(--mars-color-border)" strokeWidth="8" />
      <circle
        cx="48"
        cy="48"
        r={r}
        fill="none"
        stroke={accent}
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={offset}
        transform="rotate(-90 48 48)"
        style={{ transition: 'stroke-dashoffset 0.6s ease' }}
      />
      <text
        x="48"
        y="50"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="22"
        fontWeight="700"
        fill="var(--mars-color-text-primary)"
      >
        {Math.round(clamped)}
      </text>
      <text x="48" y="68" textAnchor="middle" fontSize="9" fill="var(--mars-color-text-tertiary)">
        / 100
      </text>
    </svg>
  );
}

function Donut({ reachable, dead }: { reachable: number; dead: number }) {
  const total = reachable + dead;
  if (total === 0) return null;
  const r = 30;
  const c = 2 * Math.PI * r;
  const reachLen = c * (reachable / total);
  return (
    <svg width="80" height="80" viewBox="0 0 80 80">
      <circle cx="40" cy="40" r={r} fill="none" stroke="#ef4444" strokeWidth="10" />
      <circle
        cx="40"
        cy="40"
        r={r}
        fill="none"
        stroke="#10b981"
        strokeWidth="10"
        strokeLinecap="butt"
        strokeDasharray={`${reachLen} ${c}`}
        transform="rotate(-90 40 40)"
      />
      <text x="40" y="44" textAnchor="middle" fontSize="14" fontWeight="700" fill="var(--mars-color-text-primary)">
        {total}
      </text>
    </svg>
  );
}

function BarRow({ label, value, max, accent, suffix }: { label: string; value: number; max: number; accent: string; suffix: string }) {
  const pct = Math.max(0, Math.min(100, max ? (value / max) * 100 : 0));
  return (
    <div>
      <div className="flex justify-between text-[10px]" style={{ color: 'var(--mars-color-text-tertiary)' }}>
        <span>{label}</span>
        <span>
          {Number.isFinite(value) ? (Math.round(value * 10) / 10).toString() : value}
          {suffix}
        </span>
      </div>
      <div className="mt-0.5 h-1.5 w-full rounded-full" style={{ background: 'var(--mars-color-surface-sunken)' }}>
        <div className="h-1.5 rounded-full" style={{ width: `${pct}%`, background: accent }} />
      </div>
    </div>
  );
}

function Kpi({ label, value, icon }: { label: string; value: number | undefined; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <div style={{ color: 'var(--mars-color-text-tertiary)' }}>{icon}</div>
      <div>
        <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--mars-color-text-tertiary)' }}>
          {label}
        </div>
        <div className="text-sm font-semibold" style={{ color: 'var(--mars-color-text-primary)' }}>
          {value ?? '—'}
        </div>
      </div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const sev = (severity || '').toLowerCase();
  const colour = sev === 'high' ? '#ef4444' : sev === 'medium' ? '#f59e0b' : '#94a3b8';
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
      style={{ background: `${colour}22`, color: colour, border: `1px solid ${colour}66` }}
    >
      {sev || '—'}
    </span>
  );
}
