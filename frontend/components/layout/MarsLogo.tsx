'use client';

import { CSSProperties } from 'react';

interface MarsLogoProps {
  size?: number;
  className?: string;
  glow?: boolean;
  animated?: boolean;
}

/**
 * Custom MARS · NewsLetter mark.
 *
 * Visual: stacked newsletter pages with a folded corner, three content lines,
 * and a sparkle in the top-right — drawn on a violet→indigo gradient tile.
 * The same component is used at 36px in the TopBar and 88px in the hero.
 */
export function MarsLogo({ size = 36, className = '', glow = true, animated = false }: MarsLogoProps) {
  const halo: CSSProperties = glow
    ? {
        position: 'absolute',
        inset: -size * 0.16,
        borderRadius: size * 0.42,
        background: 'radial-gradient(circle, rgba(139,92,246,0.55), transparent 70%)',
        filter: 'blur(14px)',
        opacity: 0.85,
      }
    : {};

  return (
    <div
      className={`relative inline-flex flex-shrink-0 ${className}`}
      style={{ width: size, height: size }}
    >
      {glow && <span aria-hidden style={halo} />}
      <div
        className={`relative flex items-center justify-center ${animated ? 'mars-gradient-animated' : ''}`}
        style={{
          width: size,
          height: size,
          borderRadius: size * 0.28,
          background: animated
            ? undefined
            : 'linear-gradient(135deg, #8b5cf6 0%, #6366f1 50%, #4f46e5 100%)',
          boxShadow: glow
            ? `0 ${size * 0.12}px ${size * 0.55}px -${size * 0.10}px rgba(99,102,241,0.55), inset 0 1px 0 rgba(255,255,255,0.22)`
            : 'inset 0 1px 0 rgba(255,255,255,0.18)',
        }}
      >
        <svg
          viewBox="0 0 32 32"
          width={size * 0.62}
          height={size * 0.62}
          fill="none"
          aria-hidden
        >
          <defs>
            <linearGradient id="mars-paper" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.98" />
              <stop offset="100%" stopColor="#ffffff" stopOpacity="0.78" />
            </linearGradient>
            <linearGradient id="mars-paper-back" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.55" />
              <stop offset="100%" stopColor="#ffffff" stopOpacity="0.30" />
            </linearGradient>
          </defs>

          {/* Back paper (offset, dimmer) */}
          <path
            d="M9.5 7.5h11.5l3 3v13.5a1.5 1.5 0 0 1-1.5 1.5h-13a1.5 1.5 0 0 1-1.5-1.5V9a1.5 1.5 0 0 1 1.5-1.5z"
            fill="url(#mars-paper-back)"
            transform="translate(-1.6 -1.6)"
            opacity="0.55"
          />

          {/* Front paper */}
          <path
            d="M9.5 5.5h11l3.5 3.5v15.5a1.5 1.5 0 0 1-1.5 1.5h-13a1.5 1.5 0 0 1-1.5-1.5V7a1.5 1.5 0 0 1 1.5-1.5z"
            fill="url(#mars-paper)"
          />

          {/* Folded corner */}
          <path
            d="M20.5 5.5v3a1.5 1.5 0 0 0 1.5 1.5h2"
            stroke="#6366f1"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="rgba(99,102,241,0.20)"
          />

          {/* Three content lines */}
          <rect x="11" y="13" width="10" height="1.6" rx="0.8" fill="#6366f1" opacity="0.85" />
          <rect x="11" y="16.5" width="11" height="1.6" rx="0.8" fill="#6366f1" opacity="0.55" />
          <rect x="11" y="20" width="7" height="1.6" rx="0.8" fill="#6366f1" opacity="0.55" />

          {/* Sparkle on top-right */}
          <g transform="translate(23 4.5)">
            <path
              d="M2.5 0 L3.2 1.8 L5 2.5 L3.2 3.2 L2.5 5 L1.8 3.2 L0 2.5 L1.8 1.8 Z"
              fill="#fde68a"
            />
            <circle cx="2.5" cy="2.5" r="0.6" fill="#ffffff" opacity="0.95" />
          </g>
        </svg>
      </div>
    </div>
  );
}
