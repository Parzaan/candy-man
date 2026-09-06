import React, { useState } from 'react';

export default function ScanForm({ onScan, loading }) {
  const [target, setTarget] = useState('');
  const [type, setType] = useState('local');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!target.trim()) return;
    onScan(target, type);
  };

  return (
    <form onSubmit={handleSubmit} className="scan-form">
      <div className="form-group">
        <label htmlFor="target-input">Repository Path or GitHub URL</label>
        <input
          id="target-input"
          type="text"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="e.g. /path/to/repo or https://github.com/org/repo"
          disabled={loading}
          required
        />
      </div>
      <div className="form-group select-group">
        <label htmlFor="type-select">Type</label>
        <select
          id="type-select"
          value={type}
          onChange={(e) => setType(e.target.value)}
          disabled={loading}
        >
          <option value="local">Local Directory</option>
          <option value="github">GitHub Repository</option>
        </select>
      </div>
      <button type="submit" disabled={loading || !target.trim()}>
        {loading ? 'Scanning...' : 'Scan Repository'}
      </button>
    </form>
  );
}
