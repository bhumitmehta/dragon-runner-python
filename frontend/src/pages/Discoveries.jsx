import { useCallback } from 'react';
import { useSmartPolling, useSelectedApp } from '../hooks';
import { getDiscoveries } from '../api';
import { FlaskConical } from 'lucide-react';

const TYPE_BADGE = {
  new_screen:     'info',
  new_transition: 'success',
  nav_script:     'info',
  verification_script: 'neutral',
  bug:            'danger',
  visual_bug:     'danger',
  crash:          'danger',
};

export default function Discoveries() {
  const { selectedApp } = useSelectedApp();
  const fetchDiscoveries = useCallback(() => getDiscoveries(200, selectedApp), [selectedApp]);
  const { data: discoveries, loading } = useSmartPolling(fetchDiscoveries, 5000, 0, [selectedApp]);

  const items = [...(discoveries || [])].reverse();

  return (
    <>
      <div className="page-header">
        <h2>Discoveries</h2>
        <p>{items.length} discoveries logged across all runs</p>
      </div>

      <div className="card">
        {loading && items.length === 0 ? (
          <div className="empty-state"><div className="spinner" style={{ margin: '0 auto' }} /></div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <div className="icon">🔍</div>
            <h3>No discoveries yet</h3>
            <p className="text-xs text-muted">Run the agent to start exploring the app</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Run</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>
                {items.slice(0, 100).map((d, i) => (
                  <tr key={i}>
                    <td className="text-xs text-muted" style={{ whiteSpace: 'nowrap' }}>
                      {d.timestamp ? new Date(d.timestamp).toLocaleString() : '—'}
                    </td>
                    <td className="mono text-xs">{(d.run_id || '').slice(0, 12)}</td>
                    <td>
                      <span className={`badge badge-${TYPE_BADGE[d.type] || 'neutral'}`}>
                        {d.type}
                      </span>
                    </td>
                    <td className="text-sm">{d.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {items.length > 100 && (
              <div className="text-xs text-muted" style={{ padding: '8px 12px' }}>
                Showing 100 of {items.length} discoveries
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
