'use client';

import Modal from '@/components/core/Modal';
import { useProviders } from '@/hooks/useProviders';

import ProviderCard from './ProviderCard';

interface ProviderSettingsProps {
  onClose: () => void;
}

/**
 * Full PaperPulse-style provider settings dialog: list every provider, status
 * badge, masked credential values, configure / edit / remove actions, with
 * encrypted vault persistence on the backend.
 *
 * Replaces the earlier read-only ``ProviderSettingsDialog`` so the user can
 * add credentials directly from the UI (e.g. paste an OpenAI key, click Test,
 * click Save, and see the available models update without restarting the
 * backend).
 */
export default function ProviderSettings({ onClose }: ProviderSettingsProps) {
  const {
    providers,
    configuredProviders,
    availableModels,
    isLoading,
    error,
    testProvider,
    saveCredentials,
    removeCredentials,
    refreshProviders,
  } = useProviders();

  const subtitle =
    configuredProviders.length > 0
      ? `${configuredProviders.length} active provider${
          configuredProviders.length !== 1 ? 's' : ''
        } · ${availableModels.length} models available`
      : 'Configure at least one LLM provider to get started';

  const footer =
    configuredProviders.length === 0 && !isLoading && !error ? (
      <p className="w-full text-center text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
        Click <strong>Configure</strong> on any provider above to add your API
        credentials. Existing <code>.env</code> credentials are detected
        automatically.
      </p>
    ) : undefined;

  return (
    <Modal open={true} onClose={onClose} title="LLM Provider Settings" size="lg" footer={footer}>
      <p className="mb-4 text-xs" style={{ color: 'var(--mars-color-text-tertiary)' }}>
        {subtitle}
      </p>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div
            className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
            style={{
              borderColor: 'var(--mars-color-border)',
              borderTopColor: 'transparent',
            }}
          />
          <span className="ml-3 text-sm" style={{ color: 'var(--mars-color-text-secondary)' }}>
            Loading providers…
          </span>
        </div>
      ) : error ? (
        <div
          role="alert"
          className="rounded-lg px-4 py-3 text-sm"
          style={{
            backgroundColor: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.2)',
            color: '#ef4444',
          }}
        >
          <div className="mb-1 font-medium">Failed to load providers</div>
          <div className="mb-3 break-all text-xs opacity-80">{error}</div>
          <button
            onClick={refreshProviders}
            className="rounded border px-3 py-1 text-xs font-medium transition-colors hover:bg-red-500/10"
            style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}
          >
            Retry
          </button>
        </div>
      ) : providers.length === 0 ? (
        <div className="py-12 text-center text-sm" style={{ color: 'var(--mars-color-text-tertiary)' }}>
          No providers registered.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {providers.map((provider) => (
            <ProviderCard
              key={provider.provider_id}
              provider={provider}
              onTest={testProvider}
              onSave={saveCredentials}
              onRemove={removeCredentials}
            />
          ))}
        </div>
      )}
    </Modal>
  );
}
