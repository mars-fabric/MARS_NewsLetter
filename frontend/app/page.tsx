'use client';

import { FileText, PanelRightClose, PanelRightOpen, ShieldCheck, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { MarsLogo } from '@/components/layout/MarsLogo';
import TopBar from '@/components/layout/TopBar';
import { NewsletterApp } from '@/components/newsletter/NewsletterApp';
import SessionSidebar, { type SessionItem } from '@/components/sessions/SessionSidebar';
import { getApiUrl } from '@/lib/config';

const SIDEBAR_MIN_WIDTH = 240;
const SIDEBAR_DEFAULT_WIDTH = 300;
const SIDEBAR_WIDTH_KEY = 'newsletter:sidebar-width';

export default function Page() {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [showTask, setShowTask] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState<number>(SIDEBAR_DEFAULT_WIDTH);
  const [isResizing, setIsResizing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (stored) {
      const n = parseInt(stored, 10);
      if (!Number.isNaN(n)) setSidebarWidth(n);
    }
  }, []);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    if (mq.matches) setSidebarOpen(false);
    const handler = (e: MediaQueryListEvent) => setSidebarOpen(!e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    if (!isResizing) return;
    const handleMove = (e: MouseEvent) => {
      const fromRight = window.innerWidth - e.clientX;
      const max = Math.floor(window.innerWidth / 2);
      const next = Math.max(SIDEBAR_MIN_WIDTH, Math.min(max, fromRight));
      setSidebarWidth(next);
    };
    const handleUp = () => {
      setIsResizing(false);
      try {
        localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
      } catch {
        // ignore
      }
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isResizing, sidebarWidth]);

  const fetchSessions = useCallback(async () => {
    try {
      const resp = await fetch(getApiUrl('/api/newsletter/recent?limit=50'));
      if (resp.ok) {
        const data: SessionItem[] = await resp.json();
        setSessions(data);
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    pollRef.current = setInterval(fetchSessions, 10000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchSessions]);

  useEffect(() => {
    if (!showTask) fetchSessions();
  }, [showTask, fetchSessions]);

  const handleNewSession = useCallback(() => {
    setActiveTaskId(null);
    setShowTask(true);
  }, []);

  const handleSelectSession = useCallback((taskId: string) => {
    setActiveTaskId(taskId);
    setShowTask(true);
  }, []);

  const handleBack = useCallback(() => {
    setShowTask(false);
    setActiveTaskId(null);
    void fetchSessions();
  }, [fetchSessions]);

  const handleTaskCreated = useCallback((taskId: string) => {
    setActiveTaskId(taskId);
    void fetchSessions();
  }, [fetchSessions]);

  const handleDeleteSession = useCallback(async (taskId: string) => {
    if (!confirm('Delete this session? This will remove all data and files.')) return;
    try {
      await fetch(getApiUrl(`/api/newsletter/${taskId}`), { method: 'DELETE' });
      setSessions((prev) => prev.filter((s) => s.task_id !== taskId));
      if (activeTaskId === taskId) {
        setShowTask(false);
        setActiveTaskId(null);
      }
    } catch {
      // ignore
    }
  }, [activeTaskId]);

  return (
    <div className="flex flex-col" style={{ height: '100vh' }}>
      <TopBar onNewSession={handleNewSession} />

      <div className="flex-1 flex min-h-0 relative">
        <div className="flex-1 min-h-0 overflow-auto relative">
          {showTask && <div className="mars-soft-bg" aria-hidden />}
          {showTask ? (
            <div className="relative z-10">
              <NewsletterApp
                key={activeTaskId || 'new'}
                resumeTaskId={activeTaskId}
                onBack={handleBack}
                onTaskCreated={handleTaskCreated}
              />
            </div>
          ) : (
            <WelcomeView onNewSession={handleNewSession} />
          )}

          <button
            onClick={() => setSidebarOpen((prev) => !prev)}
            className="absolute top-3 right-3 p-1.5 rounded-lg transition-all duration-150 hover:bg-[var(--mars-color-surface-overlay)] z-10"
            style={{ color: 'var(--mars-color-text-tertiary)' }}
            title={sidebarOpen ? 'Hide sessions' : 'Show sessions'}
          >
            {sidebarOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </div>

        {sidebarOpen && (
          <div
            role="separator"
            aria-label="Resize sessions panel"
            aria-orientation="vertical"
            onMouseDown={(e) => {
              e.preventDefault();
              setIsResizing(true);
            }}
            onDoubleClick={() => {
              setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
              try {
                localStorage.setItem(SIDEBAR_WIDTH_KEY, String(SIDEBAR_DEFAULT_WIDTH));
              } catch {
                // ignore
              }
            }}
            className="group relative w-1.5 flex-shrink-0 cursor-col-resize transition-colors duration-150"
            style={{ backgroundColor: isResizing ? 'var(--mars-color-primary)' : 'transparent' }}
            title="Drag to resize · Double-click to reset"
          >
            <div
              aria-hidden
              className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px transition-all duration-150 group-hover:w-1"
              style={{
                backgroundColor: isResizing ? 'var(--mars-color-primary)' : 'var(--mars-color-border)',
              }}
            />
            <div
              aria-hidden
              className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-0.5 h-0.5 rounded-full"
                  style={{ backgroundColor: 'var(--mars-color-text-secondary)' }}
                />
              ))}
            </div>
          </div>
        )}

        <div
          className={isResizing ? 'overflow-hidden' : 'transition-all duration-300 ease-in-out overflow-hidden'}
          style={{
            width: sidebarOpen ? `${sidebarWidth}px` : '0px',
            minWidth: sidebarOpen ? `${sidebarWidth}px` : '0px',
          }}
        >
          <SessionSidebar
            sessions={sessions}
            activeSessionId={activeTaskId}
            onSelectSession={handleSelectSession}
            onDeleteSession={handleDeleteSession}
            width={sidebarWidth}
          />
        </div>
      </div>
    </div>
  );
}

function WelcomeView({ onNewSession }: { onNewSession: () => void }) {
  const features = [
    { icon: ShieldCheck, label: 'Curated Sources', desc: 'Authentic-source validation', accent: '#22c55e' },
    { icon: Sparkles, label: 'AI Stages', desc: '5-phase pipeline', accent: '#8b5cf6' },
    { icon: FileText, label: 'PDF Newsletter', desc: 'Publication ready', accent: '#3b82f6' },
  ];

  return (
    <div className="relative h-full flex items-center justify-center p-8 overflow-hidden">
      {/* New layered background — mesh gradient + grid + drifting orbs */}
      <div className="mars-mesh-bg" aria-hidden />

      {/* Floating orbs (slow drift) */}
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        <span
          className="mars-float absolute rounded-full"
          style={{
            top: '15%',
            left: '14%',
            width: 220,
            height: 220,
            background: 'radial-gradient(circle, rgba(139,92,246,0.18), transparent 70%)',
            filter: 'blur(20px)',
            animationDuration: '11s',
          }}
        />
        <span
          className="mars-float absolute rounded-full"
          style={{
            top: '60%',
            right: '10%',
            width: 260,
            height: 260,
            background: 'radial-gradient(circle, rgba(59,130,246,0.16), transparent 70%)',
            filter: 'blur(22px)',
            animationDuration: '13s',
            animationDirection: 'reverse',
          }}
        />
        <span
          className="mars-float absolute rounded-full"
          style={{
            bottom: '8%',
            left: '38%',
            width: 180,
            height: 180,
            background: 'radial-gradient(circle, rgba(6,182,212,0.14), transparent 70%)',
            filter: 'blur(20px)',
            animationDuration: '15s',
          }}
        />

        {/* Twinkling stars */}
        {[
          { top: '12%', left: '18%', size: 4, delay: '0s' },
          { top: '22%', left: '78%', size: 3, delay: '0.6s' },
          { top: '70%', left: '12%', size: 5, delay: '1.2s' },
          { top: '80%', left: '85%', size: 3, delay: '0.3s' },
          { top: '40%', left: '8%', size: 2, delay: '1.8s' },
          { top: '55%', left: '92%', size: 4, delay: '0.9s' },
          { top: '34%', left: '46%', size: 2, delay: '2.4s' },
          { top: '88%', left: '52%', size: 2, delay: '1.5s' },
        ].map((dot, i) => (
          <span
            key={i}
            className="mars-twinkle absolute rounded-full"
            style={{
              top: dot.top,
              left: dot.left,
              width: dot.size,
              height: dot.size,
              background: 'linear-gradient(135deg, #a78bfa, #60a5fa)',
              animationDelay: dot.delay,
              boxShadow: '0 0 8px rgba(139, 92, 246, 0.6)',
            }}
          />
        ))}
      </div>

      <div className="relative z-10 flex w-full max-w-xl flex-col items-center text-center">
        {/* "PRODUCT" pill above the hero */}
        <div
          className="mars-anim-slide-up mb-5 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em]"
          style={{
            borderColor: 'rgba(139, 92, 246, 0.35)',
            background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.05))',
            color: '#c4b5fd',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
          }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: '#8b5cf6', boxShadow: '0 0 8px #8b5cf6' }} />
          AI Industry Newsletter Generation
        </div>

        {/* Hero logo */}
        <div className="mars-anim-bounce-in mars-float mb-6">
          <MarsLogo size={92} />
        </div>

        <h2
          className="mars-anim-slide-up mb-3 text-5xl font-extrabold tracking-tight"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #c7d2fe 45%, #a78bfa 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            letterSpacing: '-0.025em',
          }}
        >
          NewsLetter
        </h2>
        <p
          className="mars-anim-slide-up mars-delay-100 mb-10 mx-auto max-w-md text-sm leading-relaxed"
          style={{ color: 'var(--mars-color-text-secondary)' }}
        >
          Generate production-grade industry newsletters through AI-powered,
          multi-stage research and curation.
        </p>

        <button
          onClick={onNewSession}
          className="mars-shimmer-btn mars-anim-slide-up mars-delay-200 inline-flex items-center gap-3 rounded-2xl px-7 py-3.5 text-sm font-semibold text-white transition-all duration-200 hover:scale-[1.03] hover:shadow-2xl active:scale-[0.98]"
          style={{
            background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
            boxShadow:
              '0 10px 32px rgba(99, 102, 241, 0.50), inset 0 1px 0 rgba(255,255,255,0.20), 0 0 0 1px rgba(139,92,246,0.40)',
          }}
        >
          <FileText className="h-5 w-5" />
          Start New Newsletter
          <span className="-mr-1 opacity-70">→</span>
        </button>

        <div className="mt-12 grid grid-cols-3 gap-3">
          {features.map((feature, idx) => (
            <div
              key={feature.label}
              className={`mars-card-tilt mars-anim-slide-up mars-delay-${(idx + 3) * 100} group relative overflow-hidden rounded-2xl p-4 text-left`}
              style={{
                backgroundColor: 'var(--mars-color-surface-raised)',
                border: '1px solid var(--mars-color-border)',
                backdropFilter: 'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
              }}
            >
              <span
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-0 h-px"
                style={{ background: `linear-gradient(90deg, transparent, ${feature.accent}, transparent)` }}
              />
              <div
                className="mb-2.5 flex h-10 w-10 items-center justify-center rounded-xl transition-transform duration-200 group-hover:scale-110"
                style={{
                  background: `linear-gradient(135deg, ${feature.accent}33, ${feature.accent}11)`,
                  border: `1px solid ${feature.accent}40`,
                  boxShadow: `0 4px 14px ${feature.accent}26`,
                }}
              >
                <feature.icon className="h-4 w-4" style={{ color: feature.accent }} />
              </div>
              <p className="mb-0.5 text-xs font-semibold" style={{ color: 'var(--mars-color-text)' }}>
                {feature.label}
              </p>
              <p className="text-[10px] leading-snug" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                {feature.desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
