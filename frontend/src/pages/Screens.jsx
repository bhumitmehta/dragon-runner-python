import { useCallback } from 'react';
import { useSmartPolling, useSelectedApp } from '../hooks';
import { getScreens } from '../api';
import { useNavigate } from 'react-router-dom';
import { Monitor, ArrowRight } from 'lucide-react';

export default function Screens() {
  const { selectedApp } = useSelectedApp();
  const fetchScreens = useCallback(() => getScreens(selectedApp), [selectedApp]);
  const { data: screens, loading } = useSmartPolling(fetchScreens, 6000, 0, [selectedApp]);
  const navigate = useNavigate();

  const sorted = [...(screens || [])].sort((a, b) => (b.visit_count || 0) - (a.visit_count || 0));

  return (
    <>
      <div className="page-header">
        <h2>Screens</h2>
        <p>{sorted.length} screens discovered across all test runs</p>
      </div>

      {loading && sorted.length === 0 ? (
        <div className="empty-state"><div className="spinner" style={{ margin: '0 auto' }} /></div>
      ) : sorted.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="icon">📱</div>
            <h3>No screens discovered</h3>
            <p className="text-xs text-muted">Run the agent to discover app screens</p>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Screen</th>
                  <th>Signature</th>
                  <th>Visits</th>
                  <th>Elements</th>
                  <th>Transitions</th>
                  <th>Tags</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(s => {
                  const sig = s.sig || s.signature || s.id || '';
                  const name = s.name || sig.slice(0, 16);
                  const transCount = Object.keys(s.transitions || {}).length;
                  return (
                    <tr key={sig} style={{ cursor: 'pointer' }}
                      onClick={() => navigate(`/screens/${encodeURIComponent(sig)}`)}>
                      <td><div className="flex items-center gap-2"><Monitor size={14} style={{ color: 'var(--accent)' }} /> {name}</div></td>
                      <td><code className="mono text-xs">{sig.slice(0, 20)}</code></td>
                      <td>{s.visit_count || 0}</td>
                      <td>{(s.elements || []).length}</td>
                      <td>{transCount}</td>
                      <td>
                        {(s.tags || []).slice(0, 3).map((t, i) =>
                          <span key={i} className="badge badge-neutral" style={{ marginRight: 3 }}>{t}</span>
                        )}
                      </td>
                      <td><ArrowRight size={14} className="text-muted" /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
