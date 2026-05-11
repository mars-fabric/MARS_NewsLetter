'use client';

import { useEffect, useState } from 'react';

import { apiJson } from '@/lib/fetchWithRetry';
import { TaxonomyResponse } from '@/types/newsletter';

export interface UseTaxonomyState {
  data: TaxonomyResponse | null;
  loading: boolean;
  error: string | null;
}

export function useTaxonomy(): UseTaxonomyState {
  const [state, setState] = useState<UseTaxonomyState>({ data: null, loading: true, error: null });

  useEffect(() => {
    let alive = true;
    apiJson<TaxonomyResponse>('/api/newsletter/taxonomy')
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((err: unknown) =>
        alive && setState({ data: null, loading: false, error: err instanceof Error ? err.message : String(err) }),
      );
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
