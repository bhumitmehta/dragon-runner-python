import { useCallback } from 'react';
import { useSmartPolling, useSelectedApp } from '../hooks';
import { getBugs, getRuns, getScripts, getFeatures } from '../api';
import { Bug, FlaskConical, CheckCircle, XCircle, Clock } from 'lucide-react';

export default function TestResults() {
  const { selectedApp } = useSelectedApp();
  const fetchBugs     = useCallback(() => getBugs(selectedApp), [selectedApp]);
  const fetchRuns     = useCallback(() => getRuns(selectedApp), [selectedApp]);
  const fetchScripts  = useCallback(() => getScripts(selectedApp), [selectedApp]);
  const fetchFeatures = useCallback(() => getFeatures(selectedApp), [selectedApp]);

  const { data: bugs }     = useSmartPolling(fetchBugs, 8000, 0, [selectedApp]);
  const { data: runs }     = useSmartPolling(fetchRuns, 8000, 0, [selectedApp]);
  const { data: scripts }  = useSmartPolling(fetchScripts, 8000, 0, [selectedApp]);
  const { data: features } = useSmartPolling(fetchFeatures, 8000, 0, [selectedApp]);

  return (
    <>
      <div className="page-header">
        <h2>Test Results</h2>
        <p>Bugs, runs, scripts, and feature coverage</p>
      </div>

      {/* ── Stats ──────────────────────────────────────── */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Total Bugs</div>
          <div className="value text-danger">{bugs?.total ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">Test Runs</div>
          <div className="value">{runs?.length ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">Scripts</div>
          <div className="value">{scripts?.length ?? 0}</div>
        </div>
        <div className="stat-card">
          <div className="label">Features</div>
          <div className="value">{features?.length ?? 0}</div>
          <div className="sub">{features?.filter(f => f.tested).length ?? 0} tested</div>
        </div>
      </div>

      {/* ── Bugs ───────────────────────────────────────── */}
      <div className="card mb-4">
        <div className="card-header"><h3><Bug size={16} /> Bugs ({bugs?.total ?? 0})</h3></div>
        {(bugs?.exploration_bugs || []).length > 0 || (bugs?.script_bugs || []).length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Source</th><th>Type</th><th>Description</th><th>Time</th></tr></thead>
              <tbody>
                {(bugs?.exploration_bugs || []).map((b, i) => (
                  <tr key={`e${i}`}>
                    <td><span className="badge badge-danger">exploration</span></td>
                    <td>{b.type}</td>
                    <td>{b.description}</td>
                    <td className="text-xs text-muted">{b.timestamp ? new Date(b.timestamp).toLocaleString() : '—'}</td>
                  </tr>
                ))}
                {(bugs?.script_bugs || []).map((b, i) => (
                  <tr key={`s${i}`}>
                    <td><span className="badge badge-warning">script</span></td>
                    <td>{b.script_name}</td>
                    <td>{b.description}</td>
                    <td>—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <div className="icon">✅</div>
            <h3>No bugs found</h3>
            <p className="text-xs text-muted">Run the agent to start finding bugs</p>
          </div>
        )}
      </div>

      {/* ── Test runs ──────────────────────────────────── */}
      <div className="card mb-4">
        <div className="card-header"><h3><Clock size={16} /> Test Runs</h3></div>
        {(runs || []).length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Run ID</th><th>Status</th><th>Started</th><th>Ended</th></tr></thead>
              <tbody>
                {[...(runs || [])].reverse().slice(0, 20).map((r, i) => (
                  <tr key={i}>
                    <td className="mono text-xs">{r.run_id}</td>
                    <td>
                      <span className={`badge badge-${r.status === 'completed' ? 'success' : r.status === 'running' ? 'info' : 'neutral'}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="text-xs">{r.started_at || '—'}</td>
                    <td className="text-xs">{r.ended_at || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="text-sm text-muted" style={{ padding: 12 }}>No runs yet</div>}
      </div>

      {/* ── Verification Scripts ────────────────────────── */}
      <div className="card mb-4">
        <div className="card-header"><h3><FlaskConical size={16} /> Verification Scripts</h3></div>
        {(scripts || []).length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Result</th><th>Runs</th><th>Pass</th><th>Fail</th></tr></thead>
              <tbody>
                {(scripts || []).map((s, i) => (
                  <tr key={i}>
                    <td>{s.name || '—'}</td>
                    <td>
                      {s.last_result === 'pass' ? <span className="badge badge-success">pass</span> :
                       s.last_result === 'fail' ? <span className="badge badge-danger">fail</span> :
                       <span className="badge badge-neutral">{s.last_result || 'untested'}</span>}
                    </td>
                    <td>{s.run_count || 0}</td>
                    <td className="text-success">{s.pass_count || 0}</td>
                    <td className="text-danger">{s.fail_count || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="text-sm text-muted" style={{ padding: 12 }}>No scripts generated yet</div>}
      </div>

      {/* ── Features ───────────────────────────────────── */}
      <div className="card">
        <div className="card-header"><h3><CheckCircle size={16} /> Features</h3></div>
        {(features || []).length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Feature</th><th>Priority</th><th>Tested</th><th>Result</th></tr></thead>
              <tbody>
                {(features || []).map((f, i) => (
                  <tr key={i}>
                    <td>{f.name || f.description || '—'}</td>
                    <td>
                      <span className={`badge badge-${f.priority === 'high' ? 'danger' : f.priority === 'low' ? 'neutral' : 'warning'}`}>
                        {f.priority || 'medium'}
                      </span>
                    </td>
                    <td>{f.tested ? '✅' : '—'}</td>
                    <td>{f.test_result || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="text-sm text-muted" style={{ padding: 12 }}>No features registered</div>}
      </div>
    </>
  );
}
