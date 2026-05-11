'use client';

/**
 * useModelConfig — fetches the centralised model list from /api/models/config.
 *
 * Mirrors PaperPulse's hook of the same name so both products feel consistent.
 * Returns:
 *   availableModels  — list of {value, label} for every dropdown
 *   globalDefaults   — global role -> model name map (cmbagent YAML)
 *   workflowDefaults — per-workflow, per-stage role defaults (cmbagent YAML)
 *   customModels     — user-added models (persisted in localStorage)
 *   addCustomModel   — append a custom model id (e.g. "gpt-5-preview")
 *   removeCustomModel — drop a previously-added custom model
 *
 * Module-level cache ensures a single fetch per browser session.
 */

import { useCallback, useEffect, useState } from 'react';

import { apiJson } from '@/lib/fetchWithRetry';
import { AVAILABLE_MODELS as STATIC_FALLBACK } from '@/types/newsletter';

export interface ModelOption {
  value: string;
  label: string;
}

export interface ModelConfigResponse {
  available_models: ModelOption[];
  global_defaults: Record<string, string>;
  workflow_defaults: Record<string, Record<string, Record<string, string>>>;
}

const CUSTOM_MODELS_LS_KEY = 'mars-newsletter:custom-models';

let _cache: ModelConfigResponse | null = null;
let _fetchPromise: Promise<ModelConfigResponse | null> | null = null;

function fetchConfig(): Promise<ModelConfigResponse | null> {
  if (_fetchPromise) return _fetchPromise;
  _fetchPromise = apiJson<ModelConfigResponse>('/api/models/config')
    .then((data) => {
      _cache = data;
      return data;
    })
    .catch(() => {
      _fetchPromise = null;
      return null;
    });
  return _fetchPromise;
}

function readCustomModels(): ModelOption[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_MODELS_LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((m): ModelOption | null => {
        if (typeof m === 'string') return { value: m, label: m };
        if (m && typeof m.value === 'string') {
          return { value: m.value, label: typeof m.label === 'string' && m.label.trim() ? m.label : m.value };
        }
        return null;
      })
      .filter((m): m is ModelOption => m !== null);
  } catch {
    return [];
  }
}

function writeCustomModels(list: ModelOption[]) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CUSTOM_MODELS_LS_KEY, JSON.stringify(list));
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

export function useModelConfig() {
  const [config, setConfig] = useState<ModelConfigResponse | null>(_cache);
  const [customModels, setCustomModels] = useState<ModelOption[]>(() => readCustomModels());
  const [isLoading, setIsLoading] = useState(_cache === null);

  useEffect(() => {
    let mounted = true;
    if (_cache) {
      setConfig(_cache);
      setIsLoading(false);
      return () => {
        mounted = false;
      };
    }
    fetchConfig().then((cfg) => {
      if (!mounted) return;
      setConfig(cfg);
      setIsLoading(false);
    });
    return () => {
      mounted = false;
    };
  }, []);

  const baseModels: ModelOption[] = config?.available_models?.length
    ? config.available_models
    : STATIC_FALLBACK;

  // Custom models first (user-added are usually what they want to pick), then
  // backend list, deduped by value.
  const seen = new Set<string>();
  const availableModels: ModelOption[] = [];
  for (const m of [...customModels, ...baseModels]) {
    if (!m.value || seen.has(m.value)) continue;
    seen.add(m.value);
    availableModels.push(m);
  }

  const addCustomModel = useCallback((value: string, label?: string) => {
    const trimmedValue = value.trim();
    if (!trimmedValue) return;
    setCustomModels((prev) => {
      if (prev.some((m) => m.value === trimmedValue)) return prev;
      const next = [
        ...prev,
        { value: trimmedValue, label: (label?.trim() || trimmedValue) + ' (custom)' },
      ];
      writeCustomModels(next);
      return next;
    });
  }, []);

  const removeCustomModel = useCallback((value: string) => {
    setCustomModels((prev) => {
      const next = prev.filter((m) => m.value !== value);
      writeCustomModels(next);
      return next;
    });
  }, []);

  return {
    availableModels,
    customModels,
    addCustomModel,
    removeCustomModel,
    globalDefaults: config?.global_defaults ?? {},
    workflowDefaults: config?.workflow_defaults ?? {},
    isLoading,
  };
}

/** Resolve display-default for "(default: xxx)" labels using cmbagent YAML. */
export function resolveStageDefault(
  workflowDefaults: Record<string, Record<string, Record<string, string>>>,
  workflow: string,
  stage: number | 'default',
  role: string,
  hardcodedFallback: string,
): string {
  const wf = workflowDefaults[workflow];
  if (!wf) return hardcodedFallback;
  const stageKey = String(stage);
  return wf[stageKey]?.[role] ?? wf['default']?.[role] ?? hardcodedFallback;
}

export function invalidateModelConfigCache() {
  _cache = null;
  _fetchPromise = null;
}
