import { useSmartPolling, useAgentState, useSelectedApp } from '../hooks';
import { getCoverage, getGraphStats, getBugs, getRuns } from '../api';
import { useCallback } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';

const PIE_COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6'];

export default function Dashboard() {
  const { selectedApp } = useSelectedApp();
  const fetchCoverage   = useCallback(() => getCoverage(selectedApp), [selectedApp]);
  const fetchGraphStats = useCallback(() => getGraphStats(selectedApp), [selectedApp]);
  const fetchBugs       = useCallback(() => getBugs(selectedApp), [selectedApp]);
  const fetchRuns       = useCallback(() => getRuns(selectedApp), [selectedApp]);

  const { data: coverage }   = useSmartPolling(fetchCoverage, 5000, 0, [selectedApp]);
  const { data: graphStats } = useSmartPolling(fetchGraphStats, 5000, 0, [selectedApp]);
  const status               = useAgentState();
  const { data: bugs }       = useSmartPolling(fetchBugs, 10000, 0, [selectedApp]);
  const { data: runs }       = useSmartPolling(fetchRuns, 10000, 0, [selectedApp]);

  const screens  = coverage?.screens  || {};
  const features = coverage?.features || {};
  const scripts  = coverage?.scripts  || {};
  const archetype = coverage?.archetype;

  const barData = [
    { name: 'Screens',  discovered: screens.discovered || 0,  gaps: screens.dead_ends || 0 },
    { name: 'Features', discovered: features.total || 0,      gaps: features.untested || 0 },
    { name: 'Scripts',  discovered: scripts.total || 0,       gaps: scripts.failing || 0 },
  ];

  const pieData = [
    { name: 'Passing',  value: scripts.passing || 0 },
    { name: 'Failing',  value: scripts.failing || 0 },
  ].filter(d => d.value > 0);

  return (
    <>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Overview of your AI testing agent</p>
      </div>

      {/* ── Stat cards ─────────────────────────────────── */}
      <div className="stat-grid">
        <StatCard label="Agent State" value={status?.state || '—'}
          sub={status?.state === 'running' ? `Step ${status.current_step}/${status.max_steps}` : ''} />
        <StatCard label="Screens" value={screens.discovered ?? '—'}
          sub={`${screens.transitions ?? 0} transitions`} />
        <StatCard label="Bugs Found" value={bugs?.total ?? '—'}
          sub={bugs?.total > 0 ? '⚠ needs attention' : 'clean'} />
        <StatCard label="Test Runs" value={runs?.length ?? '—'}
          sub={archetype?.primary && archetype.primary !== 'unknown'
            ? `App type: ${archetype.primary}` : ''} />
        <StatCard label="Features" value={features.total ?? '—'}
          sub={`${features.tested ?? 0} tested`} />
        <StatCard label="Hub Screens" value={graphStats?.hub_screens?.length ?? '—'}
          sub={graphStats?.hub_screens?.[0]?.sig?.slice(0, 16) || ''} />
      </div>

      {/* ── Charts row ─────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header"><h3>Coverage Overview</h3></div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={barData} barCategoryGap="30%">
              <CartesianGrid strokeDasharray="3 3" stroke="#2e3340" />
              <XAxis dataKey="name" stroke="#6b7280" fontSize={12} />
              <YAxis stroke="#6b7280" fontSize={12} />
              <Tooltip contentStyle={{ background: '#21252f', border: '1px solid #2e3340', borderRadius: 8 }} />
              <Bar dataKey="discovered" fill="#6366f1" radius={[4,4,0,0]} name="Discovered" />
              <Bar dataKey="gaps"       fill="#ef4444" radius={[4,4,0,0]} name="Gaps" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-header"><h3>Test Scripts</h3></div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                  paddingAngle={4} dataKey="value" label={({ name, value }) => `${name}: ${value}`}>
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#21252f', border: '1px solid #2e3340', borderRadius: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-state">
              <div className="icon">🧪</div>
              <h3>No scripts yet</h3>
              <p className="text-xs text-muted">Run the agent to generate test scripts</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Coverage gaps ──────────────────────────────── */}
      {graphStats?.coverage_gaps && (
        <div className="card mt-4">
          <div className="card-header"><h3>Coverage Gaps</h3></div>
          <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
            <GapList title="Dead-End Screens" items={graphStats.coverage_gaps.dead_ends} color="danger" />
            <GapList title="Untested Screens" items={graphStats.coverage_gaps.untested_screens} color="warning" />
            <GapList title="Low Outgoing" items={graphStats.coverage_gaps.low_outgoing} color="info" />
          </div>
        </div>
      )}

      {/* ── Recent Bugs ────────────────────────────────── */}
      {(bugs?.exploration_bugs?.length > 0 || bugs?.script_bugs?.length > 0) && (
        <div className="card mt-4">
          <div className="card-header"><h3>Recent Bugs</h3></div>
          <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
            {[...(bugs.exploration_bugs || []), ...(bugs.script_bugs || [])].slice(0, 6).map((bug, i) => (
              <BugCard key={i} bug={bug} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function StatCard({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function GapList({ title, items, color }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ flex: '1 1 200px' }}>
      <div className="text-xs text-muted mb-4">{title}</div>
      {items.slice(0, 8).map((item, i) => (
        <span key={i} className={`badge badge-${color}`} style={{ marginRight: 4, marginBottom: 4 }}>
          {typeof item === 'string' ? item.slice(0, 20) : JSON.stringify(item).slice(0, 20)}
        </span>
      ))}
      {items.length > 8 && <span className="text-xs text-muted">+{items.length - 8} more</span>}
    </div>
  );
}

function BugCard({ bug }) {
  const hasScreenshot = bug.screen_signature;
  return (
    <div style={{ flex: '1 1 300px', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      {hasScreenshot && (
        <img
          src={`/api/screens/${encodeURIComponent(bug.screen_signature)}/screenshot`}
          alt="Bug screenshot"
          style={{ width: '100%', height: 150, objectFit: 'cover' }}
          onError={e => { e.target.style.display = 'none'; }}
        />
      )}
      <div style={{ padding: 12 }}>
        <div className="text-sm font-medium mb-2">{bug.description || bug.title || 'Bug'}</div>
        <div className="text-xs text-muted mb-2">
          {bug.severity && <span className={`badge badge-danger`}>{bug.severity}</span>}
          {bug.source && <span className="ml-2">{bug.source}</span>}
        </div>
        {bug.screen_name && (
          <div className="text-xs text-muted">
            Screen: {bug.screen_name}
          </div>
        )}
      </div>
    </div>
  );
}
