import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Smartphone, Play, GitFork,
  Monitor, Bug, FlaskConical, Activity,
} from 'lucide-react';
import Dashboard   from './pages/Dashboard';
import Apps        from './pages/Apps';
import AgentControl from './pages/AgentControl';
import ScreenGraph from './pages/ScreenGraph';
import Screens     from './pages/Screens';
import ScreenDetail from './pages/ScreenDetail';
import TestResults from './pages/TestResults';
import Discoveries from './pages/Discoveries';
import { usePolling, AgentProvider, AppSelectorProvider } from './hooks';
import { getAgentStatus, getApps } from './api';
import { useMemo, useState, useEffect, useCallback } from 'react';

const NAV = [
  { to: '/',            icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/apps',        icon: Smartphone,      label: 'Applications' },
  { to: '/agent',       icon: Play,            label: 'Agent Control' },
  { to: '/graph',       icon: GitFork,         label: 'Screen Graph' },
  { to: '/screens',     icon: Monitor,         label: 'Screens' },
  { to: '/results',     icon: Bug,             label: 'Test Results' },
  { to: '/discoveries', icon: FlaskConical,    label: 'Discoveries' },
];

export default function App() {
  // Single status poll for the whole app: 2s when running, 10s when idle
  const { data: status } = usePolling(getAgentStatus, 10000);
  const state = status?.state || 'idle';
  const isActive = state === 'running' || state === 'stopping';

  // Re-poll faster when agent becomes active
  const { data: fastStatus } = usePolling(getAgentStatus, isActive ? 2000 : 0, [isActive]);
  const liveStatus = (isActive && fastStatus) ? fastStatus : status;
  const liveState = liveStatus?.state || 'idle';

  // Provide agent state to all children via context
  const agentCtx = useMemo(() => liveStatus || { state: 'idle' }, [liveStatus]);

  // ── Global app selector ──────────────────────────────────────────
  const { data: apps, refresh: refreshApps } = usePolling(getApps, 0);  // one-shot

  // Persist selection in localStorage
  const [selectedApp, setSelectedAppRaw] = useState(
    () => localStorage.getItem('dragon_selected_app') || null
  );
  const setSelectedApp = useCallback((app) => {
    setSelectedAppRaw(app);
    if (app) localStorage.setItem('dragon_selected_app', app);
    else localStorage.removeItem('dragon_selected_app');
  }, []);

  // If persisted app is no longer in the profiles list, clear it
  useEffect(() => {
    if (apps && selectedApp) {
      const exists = apps.some(a => a.app_package === selectedApp);
      if (!exists) setSelectedApp(null);
    }
  }, [apps, selectedApp, setSelectedApp]);

  const appSelectorCtx = useMemo(
    () => ({ selectedApp, setSelectedApp, apps: apps || [], refreshApps }),
    [selectedApp, setSelectedApp, apps, refreshApps]
  );

  return (
    <AgentProvider value={agentCtx}>
    <AppSelectorProvider value={appSelectorCtx}>
    <div className="app-layout">
      {/* ── Sidebar ──────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>🐉 Dragon Runner</h1>
          <div className="subtitle">AI Mobile Testing Agent</div>
        </div>

        {/* ── App selector dropdown ───────────────────────── */}
        <div className="app-selector">
          <label htmlFor="app-select">Filter by App</label>
          <select
            id="app-select"
            value={selectedApp || ''}
            onChange={e => setSelectedApp(e.target.value || null)}
          >
            <option value="">All Apps</option>
            {(apps || []).map(a => (
              <option key={a.app_package} value={a.app_package}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        <nav className="sidebar-nav">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} end={to === '/'}>
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="flex items-center gap-2">
            <span className={`status-dot ${liveState}`} />
            Agent: {liveState}
            {liveState === 'running' && liveStatus?.current_step != null && (
              <span className="text-xs text-muted">
                step {liveStatus.current_step}/{liveStatus.max_steps}
              </span>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────── */}
      <main className="main-content">
        <Routes>
          <Route path="/"            element={<Dashboard />} />
          <Route path="/apps"        element={<Apps />} />
          <Route path="/agent"       element={<AgentControl />} />
          <Route path="/graph"       element={<ScreenGraph />} />
          <Route path="/screens"     element={<Screens />} />
          <Route path="/screens/:sig" element={<ScreenDetail />} />
          <Route path="/results"     element={<TestResults />} />
          <Route path="/discoveries" element={<Discoveries />} />
        </Routes>
      </main>
    </div>
    </AppSelectorProvider>
    </AgentProvider>
  );
}
