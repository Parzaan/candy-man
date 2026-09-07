import { useState } from "react";
import FunctionDetail from "./FunctionDetail";

export default function ResultsTable({ flagged }) {
  const [expandedKey, setExpandedKey] = useState(null);

  if (flagged.length === 0) {
    return (
      <div className="empty-state">
        <p>No functions were flagged in this scan.</p>
        <p className="empty-state-sub">
          Every candidate cleared at least one signal — nothing looked like a thin wrapper here.
        </p>
      </div>
    );
  }

  return (
    <div className="results-table">
      <h2>Ranked Flagged Functions ({flagged.length})</h2>

      <div className="review-notice">
        This register flags likely delegation wrappers with thin cyclomatic
        shells. Open the code and judge architectural intent yourself.
      </div>

      {flagged.map((f) => {
        const key = `${f.file}:${f.def_line}:${f.function_name}`;
        const expanded = expandedKey === key;
        return (
          <div key={key} className={`result-row${expanded ? " result-row--expanded" : ""}`}>
            <button
              type="button"
              className="result-row-header"
              onClick={() => setExpandedKey(expanded ? null : key)}
              aria-expanded={expanded}
            >
              <span className="result-rank mono">#{String(f.suspicion_rank).padStart(2, "0")}</span>
              <span className="result-name-block">
                <span className="result-name mono">{f.function_name}()</span>
                <span className="result-location mono">{f.file} · L{f.def_line}</span>
              </span>
              <span className="result-scores mono">
                Struct: {f.r_structural.toFixed(2)}
                <span className="score-divider">·</span>
                Trans: {f.transformation_computed ? f.transformation_score.toFixed(2) : "n/a"}
              </span>
              <span className="result-toggle mono">
                Inspect Evidence {expanded ? "▲" : "▼"}
              </span>
            </button>
            {expanded && <FunctionDetail func={f} />}
          </div>
        );
      })}
    </div>
  );
}