import { useState } from "react";
import { scanRepository } from "./api/scanApi";
import ScanForm from "./components/ScanForm";
import ResultsSummary from "./components/ResultsSummary";
import ResultsTable from "./components/ResultsTable";
import candyManLogo from "./assets/candy-man-logo.png";
import "./App.css";

export default function App() {
  const [status, setStatus] = useState("idle"); // idle | loading | error | results
  const [result, setResult] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);

  const runScan = async (target, type) => {
    setStatus("loading");
    setErrorInfo(null);
    try {
      const data = await scanRepository(target, type);
      setResult(data);
      setStatus("results");
    } catch (err) {
      setErrorInfo({ code: err.code, message: err.message });
      setStatus("error");
    }
  };

  const handlePickSample = (repoName) => {
    runScan(`https://github.com/${repoName}`, "github");
  };

  const handleNewScan = () => {
    setStatus("idle");
    setResult(null);
    setErrorInfo(null);
  };

  if (status === "results" && result) {
    return (
      <div className="results-screen">
        <header className="results-header">
          <div className="results-header-left">
            <img src={candyManLogo} alt="" className="logo-mark" />
            <span className="eyebrow">Candy-Man // AST.Triage</span>
          </div>
          <button type="button" className="new-scan-button" onClick={handleNewScan}>
            ← New Scan
          </button>
          <div className="results-header-right mono">
            <span>{result.repo}</span>
            <span className="score-divider">·</span>
            <span>{result.scan_duration_seconds}s</span>
          </div>
        </header>

        <div className="results-title-block">
          <h1>Triage Dossier &amp; Evidence Register</h1>
          <p>
            Structural-ratio and transformation-score evaluation for
            candidate delegation wrappers, combined by a strict AND-gate.
          </p>
        </div>

        <ResultsSummary result={result} />
        <ResultsTable flagged={result.flagged} />
      </div>
    );
  }

  return (
    <ScanForm
      status={status}
      errorInfo={errorInfo}
      onScan={runScan}
      onPickSample={handlePickSample}
    />
  );
}