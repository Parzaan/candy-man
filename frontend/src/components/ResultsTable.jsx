import { useState, useMemo } from "react";
import FunctionDetail from "./FunctionDetail";

const STRUCTURAL_THRESHOLD = 0.35;
const TRANSFORMATION_THRESHOLD = 0.30;
const HIGH_CONFIDENCE_STRUCTURAL = STRUCTURAL_THRESHOLD / 2;
const HIGH_CONFIDENCE_TRANSFORMATION = TRANSFORMATION_THRESHOLD / 2;

function getConfidenceTier(f) {
  const highConfidence =
    f.r_structural <= HIGH_CONFIDENCE_STRUCTURAL &&
    f.transformation_score <= HIGH_CONFIDENCE_TRANSFORMATION;
  return highConfidence ? "high" : "borderline";
}

function explainFlag(f) {
  const structuralPct = Math.round((1 - f.r_structural) * 100);
  let structuralPart;
  if (f.r_structural === 0) {
    structuralPart = "delegates all of its structural complexity to an external call";
  } else if (f.r_structural <= HIGH_CONFIDENCE_STRUCTURAL) {
    structuralPart = `delegates roughly ${structuralPct}% of its structural complexity externally`;
  } else {
    structuralPart = `delegates a majority (${structuralPct}%) of its structural complexity externally, though closer to the threshold than most flags`;
  }

  let transformationPart;
  if (f.transformation_score === 0) {
    transformationPart = "its return value is a direct, unmodified passthrough";
  } else if (f.transformation_score <= HIGH_CONFIDENCE_TRANSFORMATION) {
    transformationPart = "its return value shows only minimal reshaping before being returned";
  } else {
    transformationPart = "its return value shows some reshaping, though still under the flagging threshold";
  }

  return `This function ${structuralPart}, and ${transformationPart}.`;
}

export default function ResultsTable({ flagged }) {
  const [expandedKey, setExpandedKey] = useState(null);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    if (!query.trim()) return flagged;
    const q = query.trim().toLowerCase();
    return flagged.filter(
      (f) => f.function_name.toLowerCase().includes(q) || f.file.toLowerCase().includes(q)
    );
  }, [flagged, query]);

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
      <div className="results-table-header">
        <h2>Ranked Flagged Functions ({flagged.length})</h2>
        <input
          type="text"
          className="function-search"
          placeholder="Search by function name or file…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search flagged functions"
        />
      </div>

      <div className="review-notice">
        This register flags likely delegation wrappers with thin cyclomatic
        shells. Open the code and judge architectural intent yourself.
      </div>

      {filtered.length === 0 && (
        <div className="empty-state">
          <p>No flagged functions match "{query}".</p>
        </div>
      )}

      {filtered.map((f) => {
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
              <span className={`confidence-tag confidence-tag--${getConfidenceTier(f)}`}>
                {getConfidenceTier(f) === "high" ? "High confidence" : "Borderline"}
              </span>
              <span className="result-name-block">
                <span className="result-name mono">{f.function_name}()</span>
                <span className="result-location mono">{f.file} · L{f.def_line}</span>
                <span className="result-explain">{explainFlag(f)}</span>
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