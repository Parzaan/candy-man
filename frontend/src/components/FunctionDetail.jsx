export default function FunctionDetail({ func }) {
  const snippetLines = func.source_snippet.split("\n");
  const evidenceSet = new Set(func.evidence_lines);

  return (
    <div className="function-detail">
      <div className="detail-explainers">
        <div>
          <p className="detail-explainer-label mono">Structural Ratio ({func.r_structural.toFixed(2)})</p>
          <p className="detail-explainer-copy">
            How much of this function's complexity is its own logic versus
            delegated to an external call. Lower means more delegated.
          </p>
        </div>
        <div>
          <p className="detail-explainer-label mono">
            Transformation Score ({func.transformation_computed ? func.transformation_score.toFixed(2) : "n/a"})
          </p>
          <p className="detail-explainer-copy">
            {func.transformation_computed
              ? "How much the return value is computed versus passed through unchanged. Lower means closer to a pure passthrough."
              : "Could not be determined with confidence for this function — treated as not flagged."}
          </p>
        </div>
      </div>

      <div className="code-panel">
        <div className="code-panel-header mono">
          <span>{func.file}</span>
        </div>
        <pre className="code-block">
          {snippetLines.map((line, i) => {
            const lineNumber = func.snippet_start_line + i;
            const isEvidence = evidenceSet.has(lineNumber);
            return (
              <div key={lineNumber} className={`code-line${isEvidence ? " code-line--evidence" : ""}`}>
                <span className="code-line-number mono">{lineNumber}</span>
                <span className="code-line-content mono">{line}</span>
              </div>
            );
          })}
        </pre>
      </div>

      <p className="detail-reminder">
        This is a flag for review, not a verdict — open the code and judge for yourself.
      </p>
    </div>
  );
}