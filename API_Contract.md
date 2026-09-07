# API Contract: POST /scan

## Request
```json
{
  "target": "path-or-github-url",
  "type": "local"
}
```
`type` can be `"local"` or `"github"`.

## Response (success)
```json
{
  "repo": "path-or-url",
  "total_functions_scanned": 42,
  "candidates_considered": 9,
  "total_loc": 1535,
  "scan_duration_seconds": 2.99,
  "unscannable_files": ["legacy/broken_script.py"],
  "flagged": [
    {
      "function_name": "predict_collision",
      "file": "core/predictor.py",
      "def_line": 34,
      "evidence_lines": [36, 37, 41],
      "r_structural": 0.18,
      "transformation_score": 0.12,
      "transformation_computed": true,
      "suspicion_rank": 1,
      "source_snippet": "def predict_collision(...):\n    ...\n    return response.json()",
      "snippet_start_line": 34
    }
  ],
  "all_candidates": [
    {
      "function_name": "predict_collision",
      "file": "core/predictor.py",
      "def_line": 34,
      "r_structural": 0.18,
      "transformation_score": 0.12,
      "transformation_computed": true
    }
  ]
}
```

## Field notes
- `total_functions_scanned`: every function found across all successfully-parsed files.
- `candidates_considered`: functions that passed Step 1 (contain a statically-attributable third-party call) — the population actually scored. Equal to `len(all_candidates)`.
- `total_loc`: total lines of code summed across all successfully-parsed files (not including unscannable ones).
- `scan_duration_seconds`: wall-clock time the scan took, measured server-side.
- `unscannable_files`: files that failed to parse (Step 0 resilience) — always included, empty array if none. Shown to the reviewer so they know what wasn't checked, never silently dropped.
- `flagged`: only functions that passed the AND-gate (Step 4). Sorted by `suspicion_rank` ascending (1 = most suspicious), computed from the product of `r_structural` × `transformation_score` (Step 5).
- `all_candidates`: **every** scored candidate, flagged or not — added specifically to power the frontend's suspicion scatter plot, which needs the full population to show where the flagged region sits relative to everything else. Does not include `evidence_lines`, `suspicion_rank`, or `source_snippet` (those only make sense for flagged functions).
- `def_line`: the function's definition line, for jumping to it in an editor.
- `evidence_lines`: the specific lines that drove the score (external call site(s), the branches counted toward `r_structural`) — this is what lets a reviewer verify a flag in seconds instead of re-reading the whole function. Only present on `flagged` entries.
- `transformation_computed`: **important — always check this before trusting `transformation_score`.** `false` means the transformation-tracing logic bailed out (the return pattern was too complex or ambiguous to classify safely). Per the AND-gate, a function with `transformation_computed: false` is **never flagged**, so it will never appear in `flagged` — but it can still appear in `all_candidates` (shown on the scatter plot as a distinct "not computed" color, not blank).
- `source_snippet`: real source code, from the function's `def` line through its last evidence line (capped at 15 lines). Only present on `flagged` entries. Never contains fabricated content or injected annotations — exactly what's in the file.
- `snippet_start_line`: the line number of the first line in `source_snippet`, needed to correctly align `evidence_lines` (absolute line numbers) against the snippet for highlighting.

## Response (error)
```json
{
  "error": "target_unreachable",
  "message": "Could not clone 'https://github.com/owner/repo': repository not found or not accessible. Check the URL and that the repository is public."
}
```
Error codes to handle on the frontend: `target_unreachable` (bad path/URL, or a clone failure — message is now human-readable, not a raw git CLI dump), `not_a_git_repo`, `no_python_files_found`.