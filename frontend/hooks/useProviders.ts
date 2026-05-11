'use client';

/**
 * useProviders — manages LLM provider state for the Settings dialog.
 *
 * Returns:
 *   providers          — all registered providers with status + credential schema
 *   configuredProviders — only those with credentials
 *   availableModels    — models from configured providers (deduped)
 *   activeProvider     — primary active provider id
 *   isLoading          — true on first fetch
 *   error              — last fetch/mutation error (or null)
 *   testProvider()     — test credentials without storing
 *   saveCredentials()  — store credentials (vault + registry sync); throws on failure
 *   removeCredentials() — remove stored credentials; throws on failure
 *   refreshProviders() — force refresh from backend
 *
 * Ported from MARS-PaperPulse with NewsLetter's apiFetch/getApiUrl helpers.
 */

import { useCallback, useEffect, useState } from 'react';

import { invalidateModelConfigCache } from '@/hooks/useModelConfig';
import { apiFetch } from '@/lib/fetchWithRetry';
import type {
  Provider,
  ProviderTestResult,
  ProvidersListResponse,
} from '@/types/providers';

let _providersCache: ProvidersListResponse | null = null;

async function extractErrorMessage(resp: Response): Promise<string> {
  try {
    const text = await resp.text();
    if (!text) return `HTTP ${resp.status}`;
    try {
      const parsed = JSON.parse(text);
      return parsed.detail || parsed.message || parsed.error || text;
    } catch {
      return text;
    }
  } catch {
    return `HTTP ${resp.status}`;
  }
}

export function useProviders() {
  const [data, setData] = useState<ProvidersListResponse | null>(_providersCache);
  const [isLoading, setIsLoading] = useState(_providersCache === null);
  const [error, setError] = useState<string | null>(null);

  const fetchProviders = useCallback(async () => {
    try {
      const resp = await apiFetch('/api/providers');
      if (!resp.ok) throw new Error(await extractErrorMessage(resp));
      const json: ProvidersListResponse = await resp.json();
      _providersCache = json;
      setData(json);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('Failed to fetch providers:', err);
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (_providersCache) {
      setData(_providersCache);
      setIsLoading(false);
      return;
    }
    void fetchProviders();
  }, [fetchProviders]);

  const testProvider = useCallback(
    async (
      providerId: string,
      credentials: Record<string, string>,
    ): Promise<ProviderTestResult> => {
      try {
        const resp = await apiFetch(
          `/api/providers/${encodeURIComponent(providerId)}/test`,
          {
            method: 'POST',
            body: JSON.stringify({ credentials }),
          },
        );
        if (!resp.ok) {
          return { success: false, message: `HTTP ${resp.status}: ${await extractErrorMessage(resp)}` };
        }
        return (await resp.json()) as ProviderTestResult;
      } catch (err) {
        return {
          success: false,
          message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
        };
      }
    },
    [],
  );

  const saveCredentials = useCallback(
    async (
      providerId: string,
      credentials: Record<string, string>,
    ): Promise<{ status: string; message: string }> => {
      const resp = await apiFetch(
        `/api/providers/${encodeURIComponent(providerId)}/credentials`,
        {
          method: 'POST',
          body: JSON.stringify({ credentials }),
        },
      );
      if (!resp.ok) throw new Error(await extractErrorMessage(resp));
      const json = await resp.json();
      _providersCache = null;
      invalidateModelConfigCache();
      await fetchProviders();
      return {
        status: json.status ?? 'success',
        message: json.provider?.message ?? '',
      };
    },
    [fetchProviders],
  );

  const removeCredentials = useCallback(
    async (providerId: string): Promise<void> => {
      const resp = await apiFetch(
        `/api/providers/${encodeURIComponent(providerId)}/credentials`,
        { method: 'DELETE' },
      );
      if (!resp.ok) throw new Error(await extractErrorMessage(resp));
      _providersCache = null;
      invalidateModelConfigCache();
      await fetchProviders();
    },
    [fetchProviders],
  );

  const refreshProviders = useCallback(async () => {
    _providersCache = null;
    setIsLoading(true);
    setError(null);
    await fetchProviders();
  }, [fetchProviders]);

  const providers: Provider[] = data?.providers ?? [];
  const configuredProviders = providers.filter((p) => p.status !== 'not_configured');

  const availableModels = configuredProviders.flatMap((p) =>
    p.models.map((m) => ({
      value: m.model_id,
      label: m.display_name,
      provider: p.provider_id,
    })),
  );

  const seen = new Set<string>();
  const dedupedModels = availableModels.filter((m) => {
    if (seen.has(m.value)) return false;
    seen.add(m.value);
    return true;
  });

  return {
    providers,
    configuredProviders,
    availableModels: dedupedModels,
    activeProvider: data?.active_provider ?? null,
    isLoading,
    error,
    testProvider,
    saveCredentials,
    removeCredentials,
    refreshProviders,
  };
}
