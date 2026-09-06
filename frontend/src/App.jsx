import React, { useState } from 'react';
import ScanForm from './components/ScanForm';
import ResultsSummary from './components/ResultsSummary';
import ResultsTable from './components/ResultsTable';
import { scanRepository } from './api/scanApi';
import './App.css';

function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);

  const handleScan = async (target, type) => {
    setLoading(true);
    setError(null);
    try {
      const data = await scanRepository(target, type);
      setResults(data);
    } catch (err) {
      setError(err.message || 'An unexpected error occurred during scan.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="candy-man-app">
      <header className="app-header">
        <h1>🍬 Candy-Man</h1>
        <p className="app-subtitle">Genuine Implementation vs. Thin Wrapper Verifier</p>
        <p
          className="app-disclaimer"
          style={{
            fontSize: '0.85rem',
            fontStyle: 'italic',
            opacity: 0.8,
            maxWidth: '640px',
            margin: '0.5rem auto 0',
          }}
        >
          Candy-Man flags functions that look wrapper-like around third-party calls.
          Every flag is a review signal for a human reviewer to check by hand —
          never proof of cheating, plagiarism, or low-quality work.
        </p>
      </header>

      <main className="app-main">
        <ScanForm onScan={handleScan} loading={loading} />

        {error && (
          <div className="error-banner">
            <strong>Scan Error:</strong> {error}
          </div>
        )}

        {results && (
          <>
            <ResultsSummary results={results} />
            {results.unscannable_files && results.unscannable_files.length > 0 && (
              <div
                className="unscannable-notice"
                style={{ fontSize: '0.85rem', opacity: 0.8, margin: '0.5rem 0' }}
              >
                {results.unscannable_files.length} file(s) could not be parsed and were skipped:{' '}
                {results.unscannable_files.join(', ')}
              </div>
            )}
            <ResultsTable flagged={results.flagged} />
          </>
        )}
      </main>
    </div>
  );
}

export default App;
