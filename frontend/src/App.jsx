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
        <p className="app-subtitle">Wrapper Function & Technical Debt Detection Engine</p>
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
            <ResultsTable flagged={results.flagged} />
          </>
        )}
      </main>
    </div>
  );
}

export default App;
