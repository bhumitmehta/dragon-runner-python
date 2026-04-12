import React, { useEffect, useState } from 'react';
import { getSmartTestPlan, setSmartTestPlan } from '../api';

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

export default function SmartTestPlan() {
  const [plan, setPlan] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    getSmartTestPlan().then(data => {
      setPlan(data);
      setEditValue(pretty(data));
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
      await setSmartTestPlan(parsed);
      setPlan(parsed);
      setEditing(false);
      setMsg('Saved!');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setMsg('Invalid JSON or save failed');
    }
  };

  return (
    <div className="page smart-test-plan-page">
      <h2>Smart Test Plan</h2>
      {msg && <div className="msg">{msg}</div>}
      {!editing ? (
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
          </div>
        </>
      )}
    </div>
  );
}
