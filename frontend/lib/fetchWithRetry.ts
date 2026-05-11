import { getApiUrl } from './config';

export async function apiFetch(path: string, options?: RequestInit, retries = 1): Promise<Response> {
  const url = getApiUrl(path);
  const init: RequestInit = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fetch(url, init);
    } catch (err) {
      lastErr = err;
      if (attempt < retries && err instanceof TypeError) {
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      throw err;
    }
  }
  throw lastErr ?? new Error('apiFetch failed');
}

export async function apiJson<T>(path: string, options?: RequestInit, retries = 1): Promise<T> {
  const res = await apiFetch(path, options, retries);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${path}: ${body.slice(0, 500)}`);
  }
  return (await res.json()) as T;
}
