/**
 * Frontend runtime config. Exposes derived API and WebSocket URLs.
 *
 * In the browser, all calls are routed through Next.js rewrites (`next.config.js`)
 * so the page origin is the only network endpoint the browser sees — no CORS,
 * no port jumping, no mixed-content issues.
 */

const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const config = {
  apiUrl: apiBase,
  wsUrl: process.env.NEXT_PUBLIC_WS_URL || apiBase.replace(/^https?/, (m) => (m === 'https' ? 'wss' : 'ws')),
  workDir: process.env.NEXT_PUBLIC_CMBAGENT_WORK_DIR || '~/Desktop/cmbdir',
  debug: process.env.NEXT_PUBLIC_DEBUG === 'true',
};

export function getApiUrl(endpoint: string): string {
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (typeof window !== 'undefined') return path;
  return `${config.apiUrl.replace(/\/$/, '')}${path}`;
}

export function getWsUrl(endpoint: string): string {
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}${path}`;
  }
  return `${config.wsUrl.replace(/\/$/, '')}${path}`;
}
