'use client';

import { useState } from 'react';

import type { Provider, ProviderTestResult } from '@/types/providers';

import ProviderCredentialForm from './ProviderCredentialForm';
import ProviderStatusBadge from './ProviderStatusBadge';

interface ProviderCardProps {
  provider: Provider;
  onTest: (providerId: string, creds: Record<string, string>) => Promise<ProviderTestResult>;
  onSave: (providerId: string, creds: Record<string, string>) => Promise<{ status: string; message: string }>;
  onRemove: (providerId: string) => Promise<void>;
}

function ProviderIcon({ name }: { name: string }) {
  const colors: Record<string, string> = {
    OpenAI: '#10a37f',
    'Azure OpenAI': '#0078d4',
    Anthropic: '#d4a574',
    'Google Gemini': '#4285f4',
    'Mistral AI': '#ff7000',
    'AWS Bedrock': '#ff9900',
  };
  const color = colors[name] ?? '#8b5cf6';
  const letter = name.charAt(0);
  return (
    <div
      className="flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold text-white"
      style={{ backgroundColor: color }}
    >
      {letter}
    </div>
  );
}

export default function ProviderCard({ provider, onTest, onSave, onRemove }: ProviderCardProps) {
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const isConfigured = provider.status !== 'not_configured';

  const handleRemove = async () => {
    setRemoving(true);
    setRemoveError(null);
    try {
      await onRemove(provider.provider_id);
      setConfirmingRemove(false);
    } catch (err) {
      setRemoveError(err instanceof Error ? err.message : String(err));
    } finally {
      setRemoving(false);
    }
  };

  if (editing) {
    return (
      <ProviderCredentialForm
        providerName={provider.display_name}
        fields={provider.credential_fields}
        onTest={(creds) => onTest(provider.provider_id, creds)}
        onSave={async (creds) => {
          const result = await onSave(provider.provider_id, creds);
          setEditing(false);
          return result;
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  return (
    <div
      className="rounded-xl border p-4 transition-colors hover:border-[var(--mars-color-border-hover)]"
      style={{
        backgroundColor: 'var(--mars-color-surface)',
        borderColor: 'var(--mars-color-border)',
      }}
    >
      <div className="flex items-start gap-3">
        <ProviderIcon name={provider.display_name} />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2">
            <h3
              className="truncate text-sm font-semibold"
              style={{ color: 'var(--mars-color-text)' }}
            >
              {provider.display_name}
            </h3>
            <ProviderStatusBadge status={provider.status} />
          </div>

          {isConfigured && (
            <div className="space-y-0.5">
              {provider.credential_fields
                .filter((f) => f.has_value)
                .slice(0, 2)
                .map((f) => (
                  <p
                    key={f.name}
                    className="truncate font-mono text-[10px]"
                    style={{ color: 'var(--mars-color-text-tertiary)' }}
                  >
                    {f.display_name}: {f.masked_value || '****'}
                  </p>
                ))}
              <p className="text-[10px]" style={{ color: 'var(--mars-color-text-secondary)' }}>
                {provider.models.length} model{provider.models.length !== 1 ? 's' : ''} available
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        {isConfigured ? (
          <>
            <button
              onClick={() => setEditing(true)}
              className="rounded border px-2.5 py-1 text-[11px] font-medium transition-colors hover:bg-[var(--mars-color-bg-hover)]"
              style={{
                borderColor: 'var(--mars-color-border)',
                color: 'var(--mars-color-text-secondary)',
              }}
            >
              Edit
            </button>
            {confirmingRemove ? (
              <>
                <button
                  onClick={handleRemove}
                  disabled={removing}
                  className="rounded px-2.5 py-1 text-[11px] font-semibold transition-colors disabled:opacity-40"
                  style={{
                    backgroundColor: 'rgba(239,68,68,0.1)',
                    border: '1px solid rgba(239,68,68,0.3)',
                    color: '#ef4444',
                  }}
                >
                  {removing ? 'Removing…' : 'Confirm Remove'}
                </button>
                <button
                  onClick={() => {
                    setConfirmingRemove(false);
                    setRemoveError(null);
                  }}
                  disabled={removing}
                  className="rounded border px-2.5 py-1 text-[11px] font-medium transition-colors hover:bg-[var(--mars-color-bg-hover)] disabled:opacity-40"
                  style={{
                    borderColor: 'var(--mars-color-border)',
                    color: 'var(--mars-color-text-secondary)',
                  }}
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirmingRemove(true)}
                className="rounded border px-2.5 py-1 text-[11px] font-medium transition-colors hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-500"
                style={{
                  borderColor: 'var(--mars-color-border)',
                  color: 'var(--mars-color-text-tertiary)',
                }}
              >
                Remove
              </button>
            )}
          </>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-white transition-all hover:scale-[1.02] hover:shadow-lg active:scale-[0.98]"
            style={{ background: 'linear-gradient(135deg, #8b5cf6, #6366f1)' }}
          >
            Configure
          </button>
        )}
      </div>

      {removeError && (
        <div
          role="alert"
          className="mt-2 rounded px-2 py-1.5 text-[10px]"
          style={{
            backgroundColor: 'rgba(239,68,68,0.08)',
            color: '#ef4444',
            border: '1px solid rgba(239,68,68,0.2)',
          }}
        >
          Remove failed: {removeError}
        </div>
      )}
    </div>
  );
}
