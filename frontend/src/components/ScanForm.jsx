import { useState } from "react";
import candyManLogo from "../assets/candy-man-logo.png";
import githubIcon from "../assets/github-icon.png";
import folderIcon from "../assets/folder-icon.png";

// Real, verified sample repos -- run through the actual engine, not
// invented numbers. pallets/click was tested and excluded deliberately:
// its high flagged count is legitimate (its examples/ folder is full of
// genuinely one-line CLI stubs) but reads as alarming out of context for
// a quick sample list.
const SAMPLE_TARGETS = [
  { repo: "psf/requests-html", loc: "1.5k LOC" },
  { repo: "tiangolo/typer", loc: "35.6k LOC" },
];

export default function ScanForm({ status, errorInfo, onScan, onPickSample }) {
  const [mode, setMode] = useState("github"); // "github" | "local"
  const [target, setTarget] = useState("");

  const handleLogoClick = () => {
    setTarget("");
    onReset();
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!target.trim()) return;
    onScan(target.trim(), mode);
  };

  return (
    <div className="scan-screen">
      <header className="scan-header">
        <button type="button" className="logo-button" onClick={handleLogoClick} aria-label="Reset scan form">
          <img src={candyManLogo} alt="" className="logo-mark" />
        </button>
        <span className="eyebrow">CANDY-MAN</span>
      </header>

      <div className="scan-layout">
        <aside className="scan-sidebar">
          <p className="sidebar-kicker">Initialize Scan</p>
          <p className="sidebar-copy">
            Candy-Man analyzes syntax trees to flag pass-through delegation
            routines, proxy handlers, and thin API wrappers with
            disproportionately low cyclomatic entropy.
          </p>

          <div className="scope-box">
            <p className="scope-label">Scope</p>
            <ul>
              <li>Pure static AST analysis, no code execution</li>
              <li>Structural ratio threshold ≤ 0.35</li>
              <li>Transformation score threshold ≤ 0.30</li>
            </ul>
          </div>

          <div className="samples-box">
            <p className="scope-label">Sample Target Archives</p>
            {SAMPLE_TARGETS.map((s) => (
              <button
                key={s.repo}
                type="button"
                className="sample-row"
                onClick={() => onPickSample(s.repo)}
              >
                <span className="mono">{s.repo}</span>
                <span className="sample-loc mono">{s.loc}</span>
                <span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="scan-panel">
          <h1>Static Wrapper Assessment Instrument</h1>
          <p className="panel-intro">
            Candy-Man statically flags functions that may be thin wrappers
            around external APIs, presenting call signatures, invocation
            depth, and passthrough argument ratios for human review.
          </p>

          <form onSubmit={handleSubmit} className="target-form">
            <div className="target-toggle" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={mode === "github"}
                className={mode === "github" ? "active" : ""}
                onClick={() => setMode("github")}
              >
                <img src={githubIcon} alt="" /> GitHub Repository URL
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "local"}
                className={mode === "local" ? "active" : ""}
                onClick={() => setMode("local")}
              >
                <img src={folderIcon} alt="" /> Local Filesystem Path
              </button>
            </div>

            <label className="target-label" htmlFor="target-input">
              {mode === "github" ? "Remote clone endpoint (HTTPS)" : "Path"}
            </label>
            {status === "loading" ? (
              <div className="target-loading">
                <span className="pulse-dot" aria-hidden="true" />
                <span>{errorInfo?.loadingMessage || "Scanning repository…"}</span>
              </div>
            ) : (
              <input
                id="target-input"
                type="text"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder={
                  mode === "github"
                    ? "https://github.com/owner/repo"
                    : "/path/to/repo"
                }
              />
            )}

            {status === "error" && (
              <div className="error-banner">
                <p>
                  <strong>{errorInfo?.code || "scan_failed"}</strong> — {errorInfo?.message || "Something went wrong."}
                </p>
              </div>
            )}

            <p className="scope-filter-note">
              <span className="dot" aria-hidden="true" /> Scope filter: *.py only
            </p>

            <button type="submit" className="scan-cta" disabled={status === "loading"}>
              {status === "loading" ? "Scanning…" : "Scan Repository"}
            </button>
          </form>

          <p className="panel-footnote">
            Candy-Man flags functions that may be thin wrappers around
            external APIs, for you to review.
          </p>
        </main>
      </div>

      <footer className="scan-footer">
        <span className="mono">Python 3 codebases only · Candy-Man Static Analyzer · Ranked evidence triage</span>
      </footer>
    </div>
  );
}