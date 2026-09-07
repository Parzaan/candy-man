import { useState } from "react";

const STRUCTURAL_THRESHOLD = 0.35;
const TRANSFORMATION_THRESHOLD = 0.30;
const PLOT_W = 1400;
const PLOT_H = 650;
const LABEL_SPACE = 40;
const PAD = 36;

function toPlotX(r) {
  return PAD + r * (PLOT_W - PAD * 2);
}
function toPlotY(t) {
  // invert: higher transformation score plots higher up
  return PAD + (1 - t) * (PLOT_H - PAD * 2);
}

function severityColor(r, t, computed) {
  if (!computed) return "#B8AFA8"; // neutral grey for not-computed / excluded
  const flagged = r <= STRUCTURAL_THRESHOLD && t <= TRANSFORMATION_THRESHOLD;
  return flagged ? "var(--vibrant-coral)" : "var(--jasmine)";
}

function SuspicionScatter({ candidates }) {
  const [hovered, setHovered] = useState(null);
  const thresholdX = toPlotX(STRUCTURAL_THRESHOLD);
  const thresholdY = toPlotY(TRANSFORMATION_THRESHOLD);

  return (
    <div className="scatter-card">
      <p className="scatter-title">AND-Gate Suspicion Space</p>
      <p className="scatter-sub">
        Both signals must fall at or below their threshold (structural ratio ≤{" "}
        {STRUCTURAL_THRESHOLD} and transformation score ≤ {TRANSFORMATION_THRESHOLD}) for a
        function to be flagged.
      </p>

      <svg viewBox={`0 0 ${PLOT_W} ${PLOT_H + LABEL_SPACE}`} className="scatter-svg" role="img" aria-label="Scatter plot of candidate functions by structural ratio and transformation score">
        {/* flagged region shading */}
        <rect
          x={PAD}
          y={thresholdY}
          width={thresholdX - PAD}
          height={PLOT_H - PAD - thresholdY}
          fill="var(--coral-glow-tint)"
        />

        {/* axes */}
        <line x1={PAD} y1={PAD} x2={PAD} y2={PLOT_H - PAD} stroke="var(--border-soft-strong)" />
        <line x1={PAD} y1={PLOT_H - PAD} x2={PLOT_W - PAD} y2={PLOT_H - PAD} stroke="var(--border-soft-strong)" />

        {/* threshold lines */}
        <line x1={thresholdX} y1={PAD} x2={thresholdX} y2={PLOT_H - PAD} stroke="var(--vibrant-coral)" strokeDasharray="4 4" />
        <line x1={PAD} y1={thresholdY} x2={PLOT_W - PAD} y2={thresholdY} stroke="var(--vibrant-coral)" strokeDasharray="4 4" />

        {/* points */}
        {candidates.map((c) => (
          <circle
            key={`${c.file}:${c.def_line}:${c.function_name}`}
            cx={toPlotX(c.r_structural)}
            cy={toPlotY(c.transformation_computed ? c.transformation_score : 1)}
            r={hovered === c ? 16 : 12}
            fill={severityColor(c.r_structural, c.transformation_score, c.transformation_computed)}
            stroke="var(--floral-white)"
            strokeWidth="1.5"
            style={{ cursor: "pointer" }}
            onMouseEnter={() => setHovered(c)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}

        {/* axis labels */}
        <text x={PLOT_W / 2} y={PLOT_H + 26} textAnchor="middle" className="axis-label">
          Structural Ratio →
        </text>
        <text x={12} y={PLOT_H / 2 - 26} textAnchor="middle" className="axis-label" transform={`rotate(-90 12 ${PLOT_H / 2})`}>
          Transformation Score →
        </text>
      </svg>

      {hovered && (
        <div className="scatter-tooltip mono">
          <strong>{hovered.function_name}</strong>
          <div>{hovered.file}:{hovered.def_line}</div>
          <div>r={hovered.r_structural.toFixed(2)} · t={hovered.transformation_computed ? hovered.transformation_score.toFixed(2) : "n/a"}</div>
        </div>
      )}

      <div className="scatter-legend mono">
        <span><i className="legend-dot legend-dot--flagged" /> Flagged</span>
        <span><i className="legend-dot legend-dot--clear" /> Not flagged</span>
        <span><i className="legend-dot legend-dot--unknown" /> Transformation score not computed</span>
      </div>
    </div>
  );
}

export default function ResultsSummary({ result }) {
  const [showUnscannable, setShowUnscannable] = useState(false);
  const flaggedCount = result.flagged.length;
  const passRate = result.candidates_considered > 0
    ? ((result.candidates_considered / result.total_functions_scanned) * 100).toFixed(1)
    : "0.0";

  return (
    <div className="results-summary">
      <div className="stat-grid">
        <div className="stat-card">
          <p className="stat-label">Total Functions Scanned</p>
          <p className="stat-value">{result.total_functions_scanned}</p>
          <p className="stat-footnote">{result.total_loc.toLocaleString()} lines of code</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Candidates Considered</p>
          <p className="stat-value">{result.candidates_considered}</p>
          <p className="stat-footnote">{passRate}% have a direct third-party call</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Unscannable Files</p>
          <p className="stat-value">{result.unscannable_files.length}</p>
          {result.unscannable_files.length > 0 && (
            <button type="button" className="link-button" onClick={() => setShowUnscannable((s) => !s)}>
              {showUnscannable ? "Hide" : "View"} skipped files
            </button>
          )}
          {showUnscannable && (
            <ul className="unscannable-list mono">
              {result.unscannable_files.map((f) => <li key={f}>{f}</li>)}
            </ul>
          )}
        </div>
        <div className="stat-card stat-card--critical">
          <p className="stat-label">Flagged</p>
          <p className="stat-value">{flaggedCount} <span className="stat-value-sub">/ {result.candidates_considered}</span></p>
          <p className="stat-footnote">For human review — not a verdict</p>
        </div>
      </div>

      <SuspicionScatter candidates={result.all_candidates} />
    </div>
  );
}