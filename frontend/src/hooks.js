import { useState, useEffect, useCallback, useRef, useContext, createContext } from 'react';

// ── Agent status context (single shared poll for the whole app) ────

const AgentCtx = createContext({ state: 'idle' });
export const AgentProvider = AgentCtx.Provider;

/**
 * Returns the shared agent status object.
 * Only App.jsx polls the API; every other component reads from context.
 */
export function useAgentState() {
  return useContext(AgentCtx);
}

// ── Selected app context (global app filter) ──────────────────────

const AppSelectorCtx = createContext({ selectedApp: null, setSelectedApp: () => {} });
export const AppSelectorProvider = AppSelectorCtx.Provider;

/**
 * Returns { selectedApp, setSelectedApp } from the global selector.
 * selectedApp is the app_package string (or null for "All Apps").
 */
export function useSelectedApp() {
  return useContext(AppSelectorCtx);
}

/**
 * Lightweight hook that polls an API function at a given interval.
 * Returns { data, error, loading, refresh }.
 *
 * @param {Function}  apiFn        - async function that returns data
 * @param {number}    intervalMs   - polling interval (0 = one-shot fetch, no repeat)
 * @param {Array}     deps         - extra dependency array for refresh
 */
export function usePolling(apiFn, intervalMs = 3000, deps = []) {
  const [data, setData]       = useState(null);
  const [error, setError]     = useState(null);
  const [loading, setLoading] = useState(true);
  const savedFn = useRef(apiFn);

  useEffect(() => { savedFn.current = apiFn; }, [apiFn]);

  const refresh = useCallback(async () => {
    try {
      const result = await savedFn.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, deps);  // eslint-disable-line react-hooks/exhaustive-deps

  // Reset loading state when deps change so navigating to a new item
  // shows a spinner instead of stale content.
  useEffect(() => {
    setLoading(true);
    setData(null);
    setError(null);
  }, deps);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    refresh();
    if (intervalMs <= 0) return;
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}

/**
 * Smart polling: polls fast while agent is running, slow (or not at all) when idle.
 *
 * @param {Function} apiFn         - async function that returns data
 * @param {number}   activeMs      - interval when agent is running (e.g. 3000)
 * @param {number}   idleMs        - interval when agent is idle (0 = no repeat after initial fetch)
 * @param {Array}    deps          - extra dependency array
 */
export function useSmartPolling(apiFn, activeMs = 3000, idleMs = 0, deps = []) {
  const agentState = useAgentState();
  const isRunning = agentState?.state === 'running' || agentState?.state === 'stopping';
  const interval = isRunning ? activeMs : idleMs;
  return usePolling(apiFn, interval, [...deps, isRunning]);
}

/**
 * One-shot fetch (no polling). Fetches once on mount + deps change.
 */
export function useFetch(apiFn, deps = []) {
  return usePolling(apiFn, 0, deps);
}
