import { useState, useCallback, useRef, useEffect } from 'react';
import { useSmartPolling, useSelectedApp } from '../hooks';
import { getGraphD3, getGraphStats } from '../api';
import { useNavigate } from 'react-router-dom';
import ForceGraph2D from 'react-force-graph-2d';
import { ZoomIn, ZoomOut, Maximize, Info } from 'lucide-react';

export default function ScreenGraph() {
  const { selectedApp } = useSelectedApp();
  const fetchGraph = useCallback(() => getGraphD3(selectedApp), [selectedApp]);
  const fetchStats = useCallback(() => getGraphStats(selectedApp), [selectedApp]);
  const { data: graphData, loading } = useSmartPolling(fetchGraph, 8000, 0, [selectedApp]);
  const { data: stats }              = useSmartPolling(fetchStats, 8000, 0, [selectedApp]);
  const [selected, setSelected]      = useState(null);
  const graphRef = useRef();
  const navigate = useNavigate();

  // Prepare data for react-force-graph
  const fgData = graphData ? {
    nodes: (graphData.nodes || []).map(n => ({
      id: n.id,
      name: n.name || n.id?.slice(0, 16),
      visits: n.visit_count || 0,
      elements: n.elements?.length || 0,
      tags: n.tags || [],
      val: Math.max(3, Math.min(20, (n.visit_count || 1) * 2)),
    })),
    links: (graphData.links || []).map(l => ({
      source: l.source,
      target: l.target,
      element: l.element_id || '',
      reliability: l.reliability || 0,
    })),
  } : { nodes: [], links: [] };

  const handleNodeClick = useCallback((node) => {
    setSelected(node);
  }, []);

  const handleNodeDblClick = useCallback((node) => {
    navigate(`/screens/${encodeURIComponent(node.id)}`);
  }, [navigate]);

  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const label = node.name.slice(0,5) || '';
    const fontSize = Math.max(10, 12 / globalScale);
    const r = Math.sqrt(node.val) * 2.5;
    const isSelected = selected?.id === node.id;

    // Node circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = isSelected ? '#818cf8' : node.visits > 3 ? '#6366f1' : node.visits > 1 ? '#3b82f6' : '#6b7280';
    ctx.fill();

    if (isSelected) {
      ctx.strokeStyle = '#818cf8';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Label
    ctx.font = `${fontSize}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#e4e6eb';
    ctx.fillText(label, node.x, node.y + r + 3);
  }, [selected]);

  const linkCanvasObject = useCallback((link, ctx) => {
    const start = link.source;
    const end = link.target;
    if (!start?.x || !end?.x) return;

    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
    ctx.strokeStyle = `rgba(99, 102, 241, ${0.2 + (link.reliability || 0) * 0.4})`;
    ctx.lineWidth = 1;
    ctx.stroke();

    // Arrow
    const angle = Math.atan2(end.y - start.y, end.x - start.x);
    const arrowLen = 6;
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    ctx.beginPath();
    ctx.moveTo(midX, midY);
    ctx.lineTo(midX - arrowLen * Math.cos(angle - Math.PI / 6), midY - arrowLen * Math.sin(angle - Math.PI / 6));
    ctx.moveTo(midX, midY);
    ctx.lineTo(midX - arrowLen * Math.cos(angle + Math.PI / 6), midY - arrowLen * Math.sin(angle + Math.PI / 6));
    ctx.strokeStyle = 'rgba(99, 102, 241, 0.5)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }, []);

  return (
    <>
      <div className="page-header flex justify-between items-center">
        <div>
          <h2>Screen Graph</h2>
          <p>Interactive navigation map of discovered screens</p>
        </div>
        <div className="flex gap-2">
          {stats && (
            <div className="flex items-center gap-3 text-sm text-muted">
              <span>{stats.node_count} screens</span>
              <span>{stats.edge_count} transitions</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 320px' : '1fr', gap: 16 }}>
        {/* ── Graph canvas ─────────────────────────────── */}
        <div className="graph-container" style={{ height: 560 }}>
          {loading && fgData.nodes.length === 0 ? (
            <div className="empty-state">
              <div className="spinner" style={{ margin: '0 auto 16px' }} />
              <h3>Loading graph…</h3>
            </div>
          ) : fgData.nodes.length === 0 ? (
            <div className="empty-state">
              <div className="icon">🗺️</div>
              <h3>No screens discovered yet</h3>
              <p className="text-xs text-muted">Run the agent in Explorer mode to build the screen graph</p>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={fgData}
              nodeCanvasObject={nodeCanvasObject}
              linkCanvasObjectMode={() => 'replace'}
              linkCanvasObject={linkCanvasObject}
              onNodeClick={handleNodeClick}
              onNodeDblClick={handleNodeDblClick}
              backgroundColor="#0f1117"
              width={selected ? undefined : undefined}
              height={540}
              cooldownTicks={80}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={0.5}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
            />
          )}
          <div style={{ position: 'absolute', bottom: 8, right: 8, display: 'flex', gap: 4 }}>
            <button className="btn btn-secondary btn-sm" onClick={() => graphRef.current?.zoomToFit(300, 40)}>
              <Maximize size={14} />
            </button>
          </div>
        </div>

        {/* ── Detail panel ─────────────────────────────── */}
        {selected && (
          <div className="card" style={{ height: 560, overflowY: 'auto' }}>
            <div className="card-header">
              <h3 className="truncate" style={{ maxWidth: 220 }}>{selected.name}</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setSelected(null)}>✕</button>
            </div>
            <div className="text-sm" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div><span className="text-muted">Signature:</span> <code className="mono text-xs">{selected.id}</code></div>
              <div><span className="text-muted">Visits:</span> {selected.visits}</div>
              <div><span className="text-muted">Elements:</span> {selected.elements}</div>
              {selected.tags?.length > 0 && (
                <div>
                  <span className="text-muted">Tags:</span>{' '}
                  {selected.tags.map((t, i) => <span key={i} className="badge badge-neutral" style={{ marginRight: 4 }}>{t}</span>)}
                </div>
              )}
              <button className="btn btn-primary btn-sm mt-4" onClick={() => navigate(`/screens/${encodeURIComponent(selected.id)}`)}>
                <Info size={14} /> View Details
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Legend ──────────────────────────────────────── */}
      <div className="card mt-4">
        <div className="flex items-center gap-4 text-xs text-muted" style={{ flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#6b7280', display: 'inline-block' }} /> 1 visit
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#3b82f6', display: 'inline-block' }} /> 2-3 visits
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#6366f1', display: 'inline-block' }} /> 4+ visits
          </span>
          <span>| Click node to inspect. Double-click to view full screen detail.</span>
        </div>
      </div>
    </>
  );
}
