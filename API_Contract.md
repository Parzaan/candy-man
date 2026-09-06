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
      "suspicion_rank": 1
    }
  ]
}
```

## Field notes
- `total_functions_scanned`: every function found across all successfully-parsed files.
- `candidates_considered`: functions that passed Step 1 (contain a statically-attributable third-party call) — the population actually scored.
- `unscannable_files`: files that failed to parse (Step 0 resilience) — always included, empty array if none. Shown to the reviewer so they know what wasn't checked, never silently dropped.
- `flagged`: only functions that passed the AND-gate (Step 4). Sorted by `suspicion_rank` ascending (1 = most suspicious), computed from the product of `r_structural` × `transformation_score` (Step 5).
- `def_line`: the function's definition line, for jumping to it in an editor.
- `evidence_lines`: the specific lines that drove the score (external call site(s), the branches counted toward `r_structural`) — this is what lets a reviewer verify a flag in seconds instead of re-reading the whole function.
- `transformation_computed`: **important — always check this before trusting `transformation_score`.** `false` means Step 3.5's tracing bailed out (the return pattern was too complex to classify) — per the spec, a function with `transformation_computed: false` is **never flagged**, so it will never appear in `flagged` at all. This field exists for transparency/debugging, not for the frontend to act on differently.

## Response (error)
```json
{
  "error": "target_unreachable",
  "message": "Could not clone repository: 404 Not Found"
}
```
Error codes to handle on the frontend: `target_unreachable` (bad path/URL), `not_a_git_repo`, `no_python_files_found`.