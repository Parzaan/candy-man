import React from 'react';

export default function FunctionDetail({ func }) {
  if (!func) return null;

  return (
    <div className="function-detail-panel">
      <h4>Function Detail: {func.function_name}</h4>
      <div className="detail-grid">
        <div><strong>File:</strong> {func.file}</div>
        <div><strong>Definition Line:</strong> {func.def_line}</div>
        <div><strong>R Structural:</strong> {func.r_structural}</div>
        <div><strong>Transformation Score:</strong> {func.transformation_score}</div>
        <div><strong>Transformation Computed:</strong> {func.transformation_computed ? 'Yes' : 'No'}</div>
        <div><strong>Suspicion Rank:</strong> #{func.suspicion_rank}</div>
      </div>
      {func.evidence_lines && func.evidence_lines.length > 0 && (
        <div className="evidence-lines">
          <strong>Evidence Lines:</strong>
          <ul>
            {func.evidence_lines.map((line, idx) => (
              <li key={idx}>Line {line}</li>
            ))}
          </ul>
        </div>
      )}
      <p style={{ fontSize: '0.8rem', fontStyle: 'italic', opacity: 0.75, marginTop: '0.75rem' }}>
        This rank is a deterministic review-priority ordering (lower = more wrapper-like on
        both signals), not a probability of wrongdoing. Check the evidence lines yourself
        before drawing any conclusion.
      </p>
    </div>
  );
}
