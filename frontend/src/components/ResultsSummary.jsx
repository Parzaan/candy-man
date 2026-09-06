import React from 'react';

export default function ResultsSummary({ results }) {
  if (!results) return null;

  const { total_functions_scanned, candidates_considered, unscannable_files, flagged } = results;

  return (
    <div className="results-summary">
      <div className="metric-card">
        <span className="metric-value">{total_functions_scanned}</span>
        <span className="metric-label">Functions Scanned</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{candidates_considered}</span>
        <span className="metric-label">Candidates Evaluated</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{flagged ? flagged.length : 0}</span>
        <span className="metric-label">Flagged Wrappers</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{unscannable_files ? unscannable_files.length : 0}</span>
        <span className="metric-label">Unscannable Files</span>
      </div>
    </div>
  );
}
