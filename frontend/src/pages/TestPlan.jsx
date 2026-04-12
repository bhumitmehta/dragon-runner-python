import React, { useEffect, useState } from 'react';
import { getSmartTestPlan, setSmartTestPlan } from '../api';

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

export default function TestPlan() {
  const [plan, setPlan] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState('');
  const [smartPlan, setSmartPlan] = useState(null);
  const [smartEditValue, setSmartEditValue] = useState('');
  const [smartEditing, setSmartEditing] = useState(false);
  const [smartMsg, setSmartMsg] = useState('');

  useEffect(() => {
    fetch('/api/testplan')
      .then(r => r.json())
      .then(data => {
        setPlan(data);
        setEditValue(pretty(data));
      });
    getSmartTestPlan().then(data => {
      setSmartPlan(data);
      setSmartEditValue(pretty(data));
    });
  }, []);

  const handleEdit = () => setEditing(true);
  const handleCancel = () => {
    setEditValue(pretty(plan));
    setEditing(false);
  };
  const handleSave = async () => {
    try {
      const parsed = JSON.parse(editValue);
      const res = await fetch('/api/testplan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (!res.ok) throw new Error('Failed to save');
      setPlan(parsed);
      setEditing(false);
      setMsg('Saved!');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setMsg('Invalid JSON or save failed');
    }
  };
  const handleDelete = async () => {
    await fetch('/api/testplan', { method: 'DELETE' });
    setPlan({});
    setEditValue('{}');
    setEditing(false);
    setMsg('Deleted');
    setTimeout(() => setMsg(''), 2000);
  };

  // Smart Test Plan handlers
  const handleSmartEdit = () => setSmartEditing(true);
  const handleSmartCancel = () => {
    setSmartEditValue(pretty(smartPlan));
    setSmartEditing(false);
  };
  const handleSmartSave = async () => {
    try {
      const parsed = JSON.parse(smartEditValue);
      await setSmartTestPlan(parsed);
      setSmartPlan(parsed);
      setSmartEditing(false);
      setSmartMsg('Saved!');
      setTimeout(() => setSmartMsg(''), 2000);
    } catch (e) {
      setSmartMsg('Invalid JSON or save failed');
    }
  };

  return (
    <div className="page test-plan-page">
      {/* <h2>Test Plan</h2>
      {msg && <div className="msg">{msg}</div>}
      <h3>Regular Test Plan</h3> */}
      {/* {!editing ? (
        <>
          <pre style={{ background: '#f6f8fa', padding: 16, borderRadius: 6 }}>
            {pretty(plan)}
          </pre>
          <button className="btn" onClick={handleEdit}>Edit</button>
        </>
      ) : (
        <>
          <textarea
            value={editValue}
            onChange={e => setEditValue(e.target.value)}
            rows={20}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 14 }}
          />
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary" onClick={handleSave}>Save</button>
            <button className="btn" onClick={handleCancel} style={{ marginLeft: 8 }}>Cancel</button>
            <button className="btn btn-danger" onClick={handleDelete} style={{ marginLeft: 8 }}>Delete</button>
          </div>
        </>
      )} */}

      <h3 style={{ marginTop: 32 }}>Generated Test Plan</h3>
      {smartMsg && <div className="msg">{smartMsg}</div>}
      {!smartEditing ? (
        <>
          <pre style={{ background: '#10151a', padding: 16, borderRadius: 6 }}>
            {pretty(smartPlan)}
          </pre>
          <button className="btn" onClick={handleSmartEdit}>Edit</button>
        </>
      ) : (
        <>
          <textarea
            value={smartEditValue}
            onChange={e => setSmartEditValue(e.target.value)}
            rows={20}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 14 }}
          />
          <div style={{ marginTop: 8 }}>
            <button className="btn btn-primary" onClick={handleSmartSave}>Save</button>
            <button className="btn" onClick={handleSmartCancel} style={{ marginLeft: 8 }}>Cancel</button>
          </div>
        </>
      )}
    </div>
  );
}
