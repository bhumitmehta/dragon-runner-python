import { useState } from 'react';
import { usePolling, useSelectedApp } from '../hooks';
import { getApps, getActiveApp, selectApp, addApp, deleteApp, deleteAppData } from '../api';
import { Check, Plus, Package, Trash2, Database } from 'lucide-react';

export default function Apps() {
  const { data: apps, refresh: refreshApps }     = usePolling(getApps, 0);
  const { data: active, refresh: refreshActive } = usePolling(getActiveApp, 0);
  const { refreshApps: refreshGlobalApps }       = useSelectedApp();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy]     = useState(false);
  const [form, setForm]     = useState({
    name: '', app_package: '', app_activity: '.MainActivity',
    apk_path: '', source_code_dir: '', description: '',
  });
  const [msg, setMsg] = useState('');

  const handleSelect = async (name) => {
    setBusy(true);
    try {
      await selectApp(name);
      await refreshActive();
      setMsg(`Switched to "${name}"`);
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const handleAdd = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await addApp(form);
      await refreshApps();
      if (refreshGlobalApps) refreshGlobalApps();
      setAdding(false);
      setForm({ name: '', app_package: '', app_activity: '.MainActivity', apk_path: '', source_code_dir: '', description: '' });
      setMsg('App profile added');
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(''), 3000);
    }
  };

  const handleDeleteData = async (name) => {
    if (!confirm(`Delete all data for app profile "${name}"? (Profile will be preserved)`)) return;
    setBusy(true);
    try {
      const result = await deleteAppData(name);
      const deleted = result.data_deleted || {};
      const totalDeleted = Object.values(deleted).reduce((sum, count) => sum + count, 0);
      setMsg(`Data for "${name}" deleted (${totalDeleted} records)`);
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(''), 5000);
    }
  };

  return (
    <>
      <div className="page-header flex justify-between items-center">
        <div>
          <h2>Applications</h2>
          <p>Select or register mobile apps for testing</p>
        </div>
        <button className="btn btn-primary" onClick={() => setAdding(!adding)}>
          <Plus size={16} /> Add App
        </button>
      </div>

      {msg && <div className="card mb-4" style={{ padding: '10px 16px', fontSize: 13 }}>{msg}</div>}

      {/* ── Add form ─────────────────────────────────── */}
      {adding && (
        <form className="card mb-4" onSubmit={handleAdd}>
          <div className="card-header"><h3>Register New App</h3></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label>Profile Name *</label>
              <input className="form-input" required value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })} placeholder="my-app" />
            </div>
            <div className="form-group">
              <label>App Package *</label>
              <input className="form-input" required value={form.app_package}
                onChange={e => setForm({ ...form, app_package: e.target.value })} placeholder="com.example.app" />
            </div>
            <div className="form-group">
              <label>App Activity</label>
              <input className="form-input" value={form.app_activity}
                onChange={e => setForm({ ...form, app_activity: e.target.value })} />
            </div>
            <div className="form-group">
              <label>APK Path *</label>
              <input className="form-input" required value={form.apk_path}
                onChange={e => setForm({ ...form, apk_path: e.target.value })} placeholder="C:\path\to\app.apk" />
            </div>
            <div className="form-group">
              <label>Source Code Dir</label>
              <input className="form-input" value={form.source_code_dir}
                onChange={e => setForm({ ...form, source_code_dir: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Description</label>
              <input className="form-input" value={form.description}
                onChange={e => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button className="btn btn-primary" type="submit" disabled={busy}>Save</button>
            <button className="btn btn-secondary" type="button" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}

      {/* ── App list ─────────────────────────────────── */}
      <div className="card-grid">
        {(apps || []).map(app => {
          const isActive = active?.profile === app.name || active?.app_package === app.app_package;
          return (
            <div key={app.name} className="card" style={isActive ? { borderColor: 'var(--accent)' } : {}}>
              <div className="flex items-center gap-2 mb-4">
                <Package size={20} style={{ color: isActive ? 'var(--accent)' : 'var(--text-muted)' }} />
                <h3 style={{ fontSize: 15 }}>{app.name}</h3>
                {isActive && <span className="badge badge-info">Active</span>}
              </div>
              <div className="text-sm text-muted" style={{ marginBottom: 4 }}>{app.app_package}</div>
              {app.description && <div className="text-xs text-muted">{app.description}</div>}
              <div className="flex gap-2 mt-4">
                {!isActive && (
                  <button className="btn btn-secondary btn-sm" onClick={() => handleSelect(app.name)} disabled={busy}>
                    <Check size={14} /> Select
                  </button>
                )}
                <button className="btn btn-warning btn-sm" onClick={() => handleDeleteData(app.name)} disabled={busy}>
                  <Database size={14} /> Clear Data
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(app.name)} disabled={busy}>
                  <Trash2 size={14} /> Delete
                </button>
              </div>
            </div>
          );
        })}

        {(!apps || apps.length === 0) && (
          <div className="empty-state" style={{ gridColumn: '1 / -1' }}>
            <div className="icon">📱</div>
            <h3>No app profiles configured</h3>
            <p className="text-xs text-muted">Click "Add App" to register your first application</p>
          </div>
        )}
      </div>
    </>
  );
}
