import React, { useState } from 'react';
import FunctionDetail from './FunctionDetail';

export default function ResultsTable({ flagged }) {
  const [expandedRank, setExpandedRank] = useState(null);

  if (!flagged || flagged.length === 0) {
    return <div className="no-flagged">No wrapper functions flagged in this repository.</div>;
  }

  const toggleExpand = (rank) => {
    setExpandedRank(expandedRank === rank ? null : rank);
  };

  return (
    <div className="results-table-container">
      <table className="results-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Function</th>
            <th>File</th>
            <th>Line</th>
            <th>R Structural</th>
            <th>Transform Score</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {flagged.map((item) => {
            const isExpanded = expandedRank === item.suspicion_rank;
            return (
              <React.Fragment key={item.suspicion_rank}>
                <tr className={isExpanded ? 'expanded-row' : ''}>
                  <td>#{item.suspicion_rank}</td>
                  <td><code>{item.function_name}</code></td>
                  <td>{item.file}</td>
                  <td>{item.def_line}</td>
                  <td>{item.r_structural}</td>
                  <td>{item.transformation_score}</td>
                  <td>
                    <button onClick={() => toggleExpand(item.suspicion_rank)}>
                      {isExpanded ? 'Hide Details' : 'View Details'}
                    </button>
                  </td>
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={7}>
                      <FunctionDetail func={item} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
