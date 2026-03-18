import { useState, useEffect, useRef, useCallback } from 'react';
import { useAgentState, useSmartPolling, useSelectedApp } from '../hooks';
import { runAgent, runSmartTest, stopAgent, getDiscoveries } from '../api';
import { Play, Square, Send, Loader } from 'lucide-react';

export default function AgentControl() {
  const status = useAgentState();
  const { selectedApp } = useSelectedApp();
  const fetchDiscoveries = useCallback(() => getDiscoveries(50, selectedApp), [selectedApp]);
  const { data: discoveries, refresh: refreshDisc } = useSmartPolling(fetchDiscoveries, 3000, 0, [selectedApp]);
  const [task, setTask]           = useState('');
  const [mode, setMode]           = useState('task');
  const [maxSteps, setMaxSteps]   = useState(30);
  const [useExplorer, setUseExplorer] = useState(false);
  const [useVision, setUseVision] = useState(false);
  const [docsPath, setDocsPath]   = useState('');
  const [docsContent, setDocsContent] = useState('');
  const [docsFormat, setDocsFormat] = useState('text'); // text or pdf
  const [msg, setMsg]             = useState('');
  const logTopRef = useRef(null);

  const state = status?.state || 'idle';
  const isRunning = state === 'running' || state === 'stopping';

  useEffect(() => {
    logTopRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [discoveries]);

  const handleRun = async () => {
    try {
      if (mode === 'smart-test') {
        await runSmartTest({ 
          docs_path: docsPath || undefined, 
          docs_content: docsContent || undefined,
          max_steps: maxSteps 
        });
      } else {
        await runAgent({ task, mode, max_steps: maxSteps, use_explorer: useExplorer, use_vision: useVision });
      }
      setMsg('Agent started');
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    }
    setTimeout(() => setMsg(''), 3000);
  };

  const handleStop = async () => {
    try {
      await stopAgent();
      setMsg('Stop requested');
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    }
    setTimeout(() => setMsg(''), 3000);
  };

  return (
    <>
      <div className="page-header">
        <h2>Agent Control</h2>
        <p>Tell the agent what to do in natural language</p>
      </div>

      {msg && <div className="card mb-4" style={{ padding: '10px 16px', fontSize: 13 }}>{msg}</div>}

      {/* ── Status bar ────────────────────────────────── */}
      <div className="card mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`status-dot ${state}`} style={{ width: 12, height: 12 }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: 15 }}>
                {state === 'idle' && 'Ready'}
                {state === 'running' && `Running — step ${status?.current_step ?? 0} / ${status?.max_steps ?? '?'}`}
                {state === 'completed' && 'Completed'}
                {state === 'error' && 'Error'}
                {state === 'stopping' && 'Stopping…'}
              </div>
              {status?.started_at && (
                <div className="text-xs text-muted">Started: {new Date(status.started_at).toLocaleTimeString()}</div>
              )}
            </div>
          </div>
          {isRunning ? (
            <button className="btn btn-danger" onClick={handleStop}><Square size={14} /> Stop</button>
          ) : (
            <div className="flex items-center gap-2">
              {state === 'running' && <div className="spinner" />}
            </div>
          )}
        </div>
        {status?.error && (
          <div className="mt-4 text-sm text-danger" style={{ background: 'rgba(239,68,68,.08)', padding: '8px 12px', borderRadius: 6 }}>
            {status.error}
          </div>
        )}
      </div>

      {/* ── Task input ────────────────────────────────── */}
      <div className="card mb-4">
        <div className="card-header"><h3>{mode === 'smart-test' ? 'Smart Test Configuration' : 'Run Task'}</h3></div>
        
        {mode === 'smart-test' ? (
          <>
            <div className="form-group">
              <label>Documentation Source</label>
              <select className="form-select" value={docsFormat} onChange={e => setDocsFormat(e.target.value)} disabled={isRunning}>
                <option value="text">Text Content (paste directly)</option>
                <option value="pdf">File/Folder Path (.pdf, .md, .txt supported)</option>
              </select>
            </div>
            
            {docsFormat === 'text' ? (
              <div className="form-group">
                <label>Documentation Content</label>
                <textarea className="form-textarea" rows={8} value={docsContent} onChange={e => setDocsContent(e.target.value)}
                  placeholder="Paste your app documentation, requirements, or feature descriptions here..."
                  disabled={isRunning} />
              </div>
            ) : (
              <div className="form-group">
                <label>PDF/Documentation File Path</label>
                <input className="form-input" type="text" value={docsPath} onChange={e => setDocsPath(e.target.value)}
                  placeholder="e.g. /path/to/docs.pdf or /path/to/docs/folder (supports .pdf, .md, .txt)"
                  disabled={isRunning} />
              </div>
            )}
          </>
        ) : (
          <div className="form-group">
            <label>Natural Language Task</label>
            <textarea className="form-textarea" rows={3} value={task} onChange={e => setTask(e.target.value)}
              placeholder='e.g. "Login with bob@example.com / 10203040, add the first product to the cart"'
              disabled={isRunning} />
          </div>
        )}
        
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <div className="form-group">
            <label>Mode</label>
            <select className="form-select" value={mode} onChange={e => setMode(e.target.value)} disabled={isRunning}>
              <option value="task">Task (NL instruction)</option>
              <option value="explore">Explore (autonomous)</option>
              <option value="interactive">Interactive</option>
              <option value="smart-test">Smart Test (doc-driven)</option>
            </select>
          </div>
          <div className="form-group">
            <label>Max Steps</label>
            <input className="form-input" type="number" min={1} max={500} value={maxSteps}
              onChange={e => setMaxSteps(Number(e.target.value))} disabled={isRunning} />
          </div>
          {mode !== 'smart-test' && (
            <div className="form-group">
              <label>Options</label>
              <div className="flex gap-3 mt-4">
                <label className="flex items-center gap-2 text-sm" style={{ cursor: 'pointer' }}>
                  <input type="checkbox" checked={useExplorer} onChange={e => setUseExplorer(e.target.checked)} disabled={isRunning} />
                  Explorer
                </label>
                <label className="flex items-center gap-2 text-sm" style={{ cursor: 'pointer' }}>
                  <input type="checkbox" checked={useVision} onChange={e => setUseVision(e.target.checked)} disabled={isRunning} />
                  Vision
                </label>
              </div>
            </div>
          )}
        </div>
        <button className="btn btn-primary btn-lg" onClick={handleRun} disabled={isRunning || (mode === 'task' && !task.trim()) || (mode === 'smart-test' && !docsContent.trim() && !docsPath.trim())}>
          {isRunning ? <><Loader size={16} className="spinner" /> Running…</> : <><Send size={16} /> {mode === 'smart-test' ? 'Start Smart Test' : 'Run Agent'}</>}
        </button>
      </div>

      {/* ── Live discoveries feed ─────────────────────── */}
      <div className="card">
        <div className="card-header"><h3>Live Activity Feed</h3></div>
        <div style={{ maxHeight: 360, overflowY: 'auto', fontSize: 13 }}>
          <div ref={logTopRef} />
          {(discoveries || []).slice(-30).reverse().map((d, i) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span className={`badge badge-${
                d.type === 'new_screen' ? 'info' :
                d.type === 'new_transition' ? 'success' :
                d.type?.includes('bug') ? 'danger' : 'neutral'
              }`}>{d.type}</span>
              <span className="text-muted" style={{ fontSize: 11, minWidth: 60 }}>
                {d.timestamp ? new Date(d.timestamp).toLocaleTimeString() : ''}
              </span>
              <span>{d.description}</span>
            </div>
          ))}
          {(!discoveries || discoveries.length === 0) && (
            <div className="text-muted text-sm" style={{ padding: 20, textAlign: 'center' }}>
              No activity yet. Run the agent to see discoveries appear here.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
