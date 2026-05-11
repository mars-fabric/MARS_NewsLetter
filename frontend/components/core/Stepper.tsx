'use client';

import { Check, Minus, X } from 'lucide-react';
import React from 'react';

export interface StepperStep {
  id: string;
  label: string;
  status: 'pending' | 'active' | 'completed' | 'failed' | 'skipped';
  description?: string;
}

export interface StepperProps {
  steps: StepperStep[];
  orientation?: 'horizontal' | 'vertical';
  size?: 'sm' | 'md';
  onStepClick?: (index: number) => void;
}

const statusConfig: Record<string, { bg: string; border: string; icon?: React.ReactNode }> = {
  pending: {
    bg: 'var(--mars-color-surface-overlay)',
    border: 'var(--mars-color-border)',
  },
  active: {
    bg: 'var(--mars-color-primary-subtle, rgba(139,92,246,0.18))',
    border: 'var(--mars-color-primary, #8b5cf6)',
  },
  completed: {
    bg: 'rgba(34, 197, 94, 0.18)',
    border: '#22c55e',
    icon: <Check className="h-3.5 w-3.5" />,
  },
  failed: {
    bg: 'rgba(239, 68, 68, 0.18)',
    border: 'var(--mars-color-danger, #ef4444)',
    icon: <X className="h-3.5 w-3.5" />,
  },
  skipped: {
    bg: 'var(--mars-color-surface-overlay)',
    border: 'var(--mars-color-border)',
    icon: <Minus className="h-3.5 w-3.5" />,
  },
};

export default function Stepper({
  steps,
  orientation = 'horizontal',
  size = 'md',
  onStepClick,
}: StepperProps) {
  const isVertical = orientation === 'vertical';
  const dotSizeClass = size === 'sm' ? 'w-7 h-7' : 'w-9 h-9';
  const connectorMarginTop = size === 'sm' ? 13 : 17;

  if (isVertical) {
    return (
      <div className="flex flex-col" role="list">
        {steps.map((step, index) => {
          const config = statusConfig[step.status];
          const isLast = index === steps.length - 1;
          const isActive = step.status === 'active';
          const isCompleted = step.status === 'completed';
          const isFailed = step.status === 'failed';
          const clickable = !!onStepClick && (isCompleted || isActive || isFailed);
          return (
            <div key={step.id} className="flex flex-row" role="listitem">
              <div className="flex flex-col items-center">
                <StepDot
                  index={index}
                  size={dotSizeClass}
                  isActive={isActive}
                  isCompleted={isCompleted}
                  isFailed={isFailed}
                  config={config}
                  label={step.label}
                  clickable={clickable}
                  onClick={() => clickable && onStepClick && onStepClick(index)}
                />
                {!isLast && (
                  <div
                    className="my-1 min-h-[28px] w-0.5"
                    style={{ backgroundColor: isCompleted ? '#22c55e' : 'var(--mars-color-surface-overlay)' }}
                  />
                )}
              </div>
              <div
                className={`ml-3 pb-6 ${clickable ? 'group cursor-pointer' : ''}`}
                onClick={() => clickable && onStepClick && onStepClick(index)}
                title={clickable ? `Go to ${step.label}` : undefined}
              >
                <p
                  className={`${size === 'sm' ? 'text-xs' : 'text-sm'} font-semibold tracking-tight transition-colors ${clickable ? 'group-hover:text-[var(--mars-color-primary)]' : ''}`}
                  style={{
                    color: isActive || isCompleted ? 'var(--mars-color-text)' : 'var(--mars-color-text-tertiary)',
                  }}
                >
                  {step.label}
                </p>
                {step.description && (
                  <p className="mt-0.5 text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
                    {step.description}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div
      className="relative flex items-start"
      role="list"
      style={{ paddingBottom: size === 'sm' ? 28 : 32 }}
    >
      {steps.map((step, index) => {
        const config = statusConfig[step.status];
        const isLast = index === steps.length - 1;
        const isActive = step.status === 'active';
        const isCompleted = step.status === 'completed';
        const isFailed = step.status === 'failed';
        const nextStep = !isLast ? steps[index + 1] : null;
        const nextIsCompletedOrActive =
          !!nextStep && (nextStep.status === 'completed' || nextStep.status === 'active');
        const clickable = !!onStepClick && (isCompleted || isActive || isFailed);

        return (
          <React.Fragment key={step.id}>
            <div className="relative flex-shrink-0" role="listitem">
              <StepDot
                index={index}
                size={dotSizeClass}
                isActive={isActive}
                isCompleted={isCompleted}
                isFailed={isFailed}
                config={config}
                label={step.label}
                clickable={clickable}
                onClick={() => clickable && onStepClick && onStepClick(index)}
              />
              <div
                className={`absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-center ${clickable ? 'group cursor-pointer' : ''}`}
                style={{ top: 'calc(100% + 8px)' }}
                onClick={() => clickable && onStepClick && onStepClick(index)}
                title={clickable ? `Go to ${step.label}` : undefined}
              >
                <p
                  className={`${size === 'sm' ? 'text-xs' : 'text-sm'} font-semibold tracking-tight transition-colors ${clickable ? 'group-hover:text-[var(--mars-color-primary)]' : ''}`}
                  style={{
                    color: isActive || isCompleted ? 'var(--mars-color-text)' : 'var(--mars-color-text-tertiary)',
                  }}
                >
                  {step.label}
                </p>
                {step.description && (
                  <p
                    className="mt-0.5 text-[10px]"
                    style={{ color: 'var(--mars-color-text-tertiary)' }}
                  >
                    {step.description}
                  </p>
                )}
              </div>
            </div>

            {!isLast && (
              <div
                className="relative flex-1 overflow-hidden rounded-full"
                style={{
                  height: '2px',
                  marginTop: `${connectorMarginTop}px`,
                  backgroundColor: 'var(--mars-color-surface-overlay)',
                }}
              >
                <div
                  className="absolute inset-0 rounded-full transition-all duration-500"
                  style={{
                    background: isCompleted
                      ? 'linear-gradient(90deg, #22c55e, #16a34a)'
                      : isActive
                        ? 'linear-gradient(90deg, #22c55e, #8b5cf6)'
                        : 'transparent',
                    width: isCompleted
                      ? '100%'
                      : isActive && nextIsCompletedOrActive
                        ? '100%'
                        : isActive
                          ? '50%'
                          : '0%',
                    boxShadow: isCompleted || isActive ? '0 0 8px rgba(99, 102, 241, 0.45)' : 'none',
                  }}
                />
              </div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

interface StepDotProps {
  index: number;
  size: string;
  isActive: boolean;
  isCompleted: boolean;
  isFailed: boolean;
  config: { bg: string; border: string; icon?: React.ReactNode };
  label: string;
  clickable: boolean;
  onClick: () => void;
}

function StepDot({
  index,
  size,
  isActive,
  isCompleted,
  isFailed,
  config,
  label,
  clickable,
  onClick,
}: StepDotProps) {
  return (
    <div className="relative flex-shrink-0">
      {isActive && (
        <span
          aria-hidden
          className="absolute inset-0 animate-ping rounded-full"
          style={{ background: 'radial-gradient(circle, rgba(139, 92, 246, 0.45), transparent 70%)' }}
        />
      )}
      <div
        className={`${size} relative flex items-center justify-center rounded-full text-xs font-bold transition-all duration-300 ${clickable ? 'cursor-pointer hover:scale-110 hover:brightness-110' : ''}`}
        style={{
          background: isActive
            ? 'linear-gradient(135deg, #8b5cf6, #6366f1)'
            : isCompleted
              ? 'linear-gradient(135deg, #22c55e, #16a34a)'
              : config.bg,
          border: isActive ? '2px solid transparent' : `2px solid ${config.border}`,
          color:
            isActive || isCompleted
              ? 'white'
              : isFailed
                ? 'var(--mars-color-danger, #ef4444)'
                : 'var(--mars-color-text-tertiary)',
          boxShadow: isActive
            ? '0 0 0 4px rgba(139, 92, 246, 0.18), 0 4px 14px rgba(99, 102, 241, 0.45)'
            : isCompleted
              ? '0 2px 8px rgba(34, 197, 94, 0.30)'
              : 'none',
        }}
        onClick={onClick}
        onKeyDown={(e) => {
          if (clickable && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            onClick();
          }
        }}
        role={clickable ? 'button' : undefined}
        tabIndex={clickable ? 0 : undefined}
        title={clickable ? `Go to ${label}` : undefined}
        aria-label={clickable ? `Go to ${label}` : label}
      >
        {config.icon || (isActive ? <span className="h-2 w-2 animate-pulse rounded-full bg-white" /> : index + 1)}
      </div>
    </div>
  );
}
