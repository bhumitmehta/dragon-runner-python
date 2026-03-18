/**
 * API client for the Dragon Runner backend (FastAPI on port 8000).
 *
 * Every function returns a plain JS object (already parsed from JSON).
 * Errors are thrown as Error instances with the server detail message.
 */

const BASE = '/api';

async function request(path, opts = {}) {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

/** Build a query-string suffix like "?app=com.foo&extra=1" from an object,
 *  skipping null/undefined values. */
function qs(params = {}) {
  const parts = Object.entries(params)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/* ── Apps ──────────────────────────────────────────────────────────── */

export const getApps        = ()     => request('/apps');
export const getActiveApp   = ()     => request('/apps/active');
export const selectApp      = (name) => request('/apps/select', { method: 'POST', body: JSON.stringify({ profile_name: name }) });
export const addApp         = (data) => request('/apps/add',    { method: 'POST', body: JSON.stringify(data) });
export const deleteApp      = (name) => request(`/apps/${encodeURIComponent(name)}`, { method: 'DELETE' });
export const deleteAppData  = (name) => request(`/apps/${encodeURIComponent(name)}/data`, { method: 'DELETE' });

/* ── Agent ─────────────────────────────────────────────────────────── */

export const runAgent       = (data) => request('/agent/run',   { method: 'POST', body: JSON.stringify(data) });
export const runSmartTest   = (data) => request('/agent/smart-test', { method: 'POST', body: JSON.stringify(data) });
export const stopAgent      = ()     => request('/agent/stop',  { method: 'POST' });
export const getAgentStatus = ()     => request('/agent/status');

/* ── Graph ─────────────────────────────────────────────────────────── */

export const getGraphD3       = (app)          => request(`/graph${qs({ app })}`);
export const getGraphCytoscape = (app)         => request(`/graph/cytoscape${qs({ app })}`);
export const getGraphMermaid  = (app)          => request(`/graph/mermaid${qs({ app })}`);
export const getGraphStats    = (app)          => request(`/graph/stats${qs({ app })}`);
export const getGraphPath     = (from, to)     => request(`/graph/path?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
export const getUnreachable   = (root = '')    => request(`/graph/unreachable?root=${encodeURIComponent(root)}`);
export const getCycles        = ()             => request('/graph/cycles');

/* ── Screens ───────────────────────────────────────────────────────── */

export const getScreens       = (app)  => request(`/screens${qs({ app })}`);
export const getScreen        = (sig)  => request(`/screens/${encodeURIComponent(sig)}`);
export const getScreenNeighbors = (sig) => request(`/screens/${encodeURIComponent(sig)}/neighbors`);
export const getScreenshotUrl = (sig)  => `${BASE}/screens/${encodeURIComponent(sig)}/screenshot`;

/* ── Dashboard ─────────────────────────────────────────────────────── */

export const getRuns          = (app)        => request(`/runs${qs({ app })}`);
export const getBugs          = (app)        => request(`/bugs${qs({ app })}`);
export const getCoverage      = (app)        => request(`/coverage${qs({ app })}`);
export const getScripts       = (app)        => request(`/scripts${qs({ app })}`);
export const getFeatures      = (app)        => request(`/features${qs({ app })}`);
export const getDiscoveries   = (limit = 50, app) => request(`/discoveries${qs({ limit, app })}`);
export const getElementBehaviors = (sig, app) => request(`/element-behaviors${qs({ screen_sig: sig, app })}`);

/* ── Meta ──────────────────────────────────────────────────────────── */

export const getHealth    = () => request('/health');
export const getKbSummary = () => request('/kb/summary');
