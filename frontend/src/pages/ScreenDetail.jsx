import { useParams, useNavigate, Link } from 'react-router-dom';
import { useFetch } from '../hooks';
import { getScreen, getScreenNeighbors, getScreenshotUrl, getElementBehaviors } from '../api';
import { ArrowLeft, ArrowRight, Image, Code, MousePointer2 } from 'lucide-react';

export default function ScreenDetail() {
  const { sig } = useParams();
  const navigate = useNavigate();
  const { data: screen, loading }   = useFetch(() => getScreen(sig), [sig]);
  const { data: neighbors }          = useFetch(() => getScreenNeighbors(sig), [sig]);
  const { data: behaviors }           = useFetch(() => getElementBehaviors(sig), [sig]);

  if (loading) return <div className="empty-state"><div className="spinner" style={{ margin: '0 auto' }} /></div>;
  if (!screen) return <div className="empty-state"><h3>Screen not found</h3></div>;

  const name = screen.name || sig.slice(0, 20);
  const transitions = screen.transitions || {};
  const elements = screen.elements || [];
  const predecessors = neighbors?.predecessors || [];
  const successors   = neighbors?.successors || [];

  return (
    <>
      <div className="page-header">
        <div className="flex items-center gap-3">
          <button className="btn btn-secondary btn-sm" onClick={() => navigate(-1)}><ArrowLeft size={14} /></button>
          <div>
            <h2>{name}</h2>
            <p className="mono text-xs">{sig}</p>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* ── Screenshot ──────────────────────────────── */}
        <div className="card">
          <div className="card-header"><h3><Image size={6} /> Screenshot</h3></div>
          <img
            src={getScreenshotUrl(sig)}
            alt={`Screenshot of ${name}`}
            style={{ width: '40%', borderRadius: 6, background: '#000' }}
            onError={e => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'block'; }}
          />
          <div className="empty-state" style={{ display: 'none' }}>
            <div className="icon">📸</div>
            <p className="text-xs text-muted">No screenshot available</p>
          </div>
        </div>

        {/* ── Metadata ────────────────────────────────── */}
        <div className="flex flex-col gap-4">
          <div className="card">
            <div className="card-header"><h3>Info</h3></div>
            <div className="text-sm" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px' }}>
              <span className="text-muted">Visits</span><span>{screen.visit_count || 0}</span>
              <span className="text-muted">First seen</span><span className="text-xs">{screen.first_seen || '—'}</span>
              <span className="text-muted">Last seen</span><span className="text-xs">{screen.last_seen || '—'}</span>
              <span className="text-muted">Elements</span><span>{elements.length}</span>
              <span className="text-muted">Input fields</span><span>{(screen.input_fields || []).length}</span>
              <span className="text-muted">Description</span><span>{screen.description || '—'}</span>
            </div>
            {(screen.tags || []).length > 0 && (
              <div className="mt-4">
                {screen.tags.map((t, i) => <span key={i} className="badge badge-neutral" style={{ marginRight: 4 }}>{t}</span>)}
              </div>
            )}
          </div>

          {/* ── Transitions ───────────────────────────── */}
          <div className="card">
            <div className="card-header"><h3><ArrowRight size={16} /> Transitions ({Object.keys(transitions).length})</h3></div>
            {Object.keys(transitions).length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Element / Action</th><th>Target Screen</th></tr></thead>
                  <tbody>
                    {Object.entries(transitions).map(([action, target]) => (
                      <tr key={action}>
                        <td className="mono text-xs">{action}</td>
                        <td>
                          <Link to={`/screens/${encodeURIComponent(target)}`} className="mono text-xs">
                            {target.slice(0, 24)}
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="text-sm text-muted">No transitions recorded</div>}
          </div>
        </div>
      </div>

      {/* ── Neighbors ──────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }} className="mt-4">
        <div className="card">
          <div className="card-header"><h3><ArrowLeft size={16} /> Predecessors ({predecessors.length})</h3></div>
          {predecessors.length > 0 ? (
            <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
              {predecessors.map((p, i) => {
                const pSig = typeof p === 'string' ? p : p?.sig || '';
                const pLabel = p?.element_id ? `${pSig.slice(0, 12)} (${p.element_id})` : pSig.slice(0, 20);
                return (
                  <Link key={i} to={`/screens/${encodeURIComponent(pSig)}`}
                    className="badge badge-info" style={{ cursor: 'pointer' }}>{pLabel}</Link>
                );
              })}
            </div>
          ) : <div className="text-sm text-muted">No predecessors (entry point?)</div>}
        </div>
        <div className="card">
          <div className="card-header"><h3><ArrowRight size={16} /> Successors ({successors.length})</h3></div>
          {successors.length > 0 ? (
            <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
              {successors.map((s, i) => {
                const sSig = typeof s === 'string' ? s : s?.sig || '';
                const sLabel = s?.element_id ? `${sSig.slice(0, 12)} (${s.element_id})` : sSig.slice(0, 20);
                return (
                  <Link key={i} to={`/screens/${encodeURIComponent(sSig)}`}
                    className="badge badge-success" style={{ cursor: 'pointer' }}>{sLabel}</Link>
                );
              })}
            </div>
          ) : <div className="text-sm text-muted">No successors (dead-end)</div>}
        </div>
      </div>

      {/* ── Elements ───────────────────────────────────── */}
      <div className="card mt-4">
        <div className="card-header"><h3><Code size={16} /> Elements ({elements.length})</h3></div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {elements.slice(0, 60).map((el, i) => (
            <span key={i} className="badge badge-neutral mono">{el}</span>
          ))}
          {elements.length > 60 && <span className="text-xs text-muted">+{elements.length - 60} more</span>}
        </div>
      </div>

      {/* ── Learned Behaviors ──────────────────────────── */}
      {behaviors && behaviors.length > 0 && (
        <div className="card mt-4">
          <div className="card-header"><h3><MousePointer2 size={16} /> Learned Element Behaviors ({behaviors.length})</h3></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Element</th><th>Behavior</th><th>Clicks</th><th>Nav Count</th><th>Targets</th></tr></thead>
              <tbody>
                {behaviors.slice(0, 30).map((b, i) => (
                  <tr key={i}>
                    <td className="mono text-xs">{b.element_id}</td>
                    <td>
                      <span className={`badge badge-${b.last_behavior === 'navigates' ? 'success' : b.last_behavior === 'stays' ? 'neutral' : 'info'}`}>
                        {b.last_behavior}
                      </span>
                    </td>
                    <td>{b.click_count}</td>
                    <td>{b.nav_count}</td>
                    <td>{(b.known_targets || []).length > 0
                      ? b.known_targets.slice(0, 2).map(t => t.slice(0, 12)).join(', ')
                      : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
