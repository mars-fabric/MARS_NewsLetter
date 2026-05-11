'use client';

import { Moon, Plus, Settings, Sun } from 'lucide-react';
import { useState } from 'react';

import ProviderSettings from '@/components/settings/ProviderSettings';
import { useTheme } from '@/contexts/ThemeContext';

import { MarsLogo } from './MarsLogo';

interface TopBarProps {
  onNewSession: () => void;
}

export default function TopBar({ onNewSession }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <>
      <header
        className="relative flex-shrink-0 border-b"
        style={{
          backgroundColor: 'var(--mars-color-surface-raised)',
          borderColor: 'var(--mars-color-border)',
        }}
        role="banner"
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{
            background: 'linear-gradient(90deg, transparent 0%, rgba(139,92,246,0.5) 30%, rgba(99,102,241,0.5) 70%, transparent 100%)',
          }}
        />
        <div className="flex items-center justify-between px-5" style={{ height: '56px' }}>
          <div className="flex items-center gap-3">
            <MarsLogo size={36} />
            <div className="leading-tight">
              <h1
                className="text-[15px] font-bold tracking-tight"
                style={{ fontFamily: 'var(--mars-font-sans)' }}
              >
                <span
                  style={{
                    background: 'linear-gradient(135deg, #fff 0%, #cbd5e1 100%)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    backgroundClip: 'text',
                  }}
                >
                  MARS
                </span>
                <span className="mx-1" style={{ color: 'var(--mars-color-text-tertiary)' }}>·</span>
                <span
                  style={{
                    background: 'linear-gradient(135deg, #a78bfa 0%, #6366f1 100%)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    backgroundClip: 'text',
                  }}
                >
                  NewsLetter
                </span>
              </h1>
              <p className="text-[10.5px] mt-0.5" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                AI Industry Newsletter Generation
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSettings(true)}
              className="p-2 rounded-lg transition-all duration-150 hover:bg-[var(--mars-color-bg-hover)] hover:scale-[1.05] active:scale-[0.95]"
              style={{ color: 'var(--mars-color-text-secondary)' }}
              aria-label="LLM provider settings"
              title="LLM provider settings"
            >
              <Settings className="w-4 h-4" />
            </button>

            <button
              onClick={toggleTheme}
              className="p-2 rounded-lg transition-all duration-150 hover:bg-[var(--mars-color-bg-hover)] hover:scale-[1.05] active:scale-[0.95]"
              style={{ color: 'var(--mars-color-text-secondary)' }}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              title={`${theme === 'dark' ? 'Light' : 'Dark'} mode`}
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>

            <button
              onClick={onNewSession}
              className="mars-shimmer-btn flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold text-white transition-all duration-150 hover:shadow-lg hover:scale-[1.04] active:scale-[0.97]"
              style={{
                background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
                boxShadow: '0 4px 14px rgba(99, 102, 241, 0.40), inset 0 1px 0 rgba(255,255,255,0.18)',
              }}
            >
              <Plus className="w-3.5 h-3.5" />
              New Session
            </button>
          </div>
        </div>
      </header>

      {showSettings && <ProviderSettings onClose={() => setShowSettings(false)} />}
    </>
  );
}
