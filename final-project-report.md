# Final Project Report: Candy-Man

## Executive Summary
Candy-Man identifies thin wrapper functions around external third-party APIs using pure AST static analysis (Python's built-in `ast` module — no ML, no LLMs, fully deterministic). It is a **triage tool**: a flag is a signal for a human reviewer to check by hand, never proof of cheating, plagiarism, or low code quality.

The pipeline follows `implementation-spec.md`'s five-step architecture:

1. **Repo Loading** (`repo_loader.py`) — local path or GitHub clone, per-file safe `ast.parse`, so one malformed file never aborts a scan.
2. **Candidacy Filtering** (`candidacy.py` + `classifier.py`) — keep only functions with ≥1 statically-attributable direct third-party call.
3. **Structural Scoring** (`structural.py`) — `R_structural`: internal logic vs. third-party delegation, with a housekeeping discount so padding a wrapper with validation guards doesn't inflate its score.
4. **Transformation Scoring** (`transformation.py`) — does the return value reflect real computation on the external result, or is it a passthrough? Narrow backward-tracing only, never full symbolic execution.
5. **AND-Gate & Ranking** (`scorer.py`) — a function is flagged only when *both* signals independently look wrapper-like; flagged functions are ranked by `r_structural × transformation_score` ascending.

## A Note on Calibration
`implementation-spec.md` fixes the pipeline architecture and the required cases (housekeeping discount, passthrough/extraction/arithmetic/string/same-key-merge/multi-return/no-op transformation cases, the AND-gate, product ranking) but does not specify exact numeric weights or thresholds. This implementation's specific constants — documented inline as comments at the top of `structural.py`, `transformation.py`, and `scorer.py` — are calibrated defaults, chosen so the worked example in `API_CONTRACT.md` (`r_structural: 0.18`, `transformation_score: 0.12`, both flagged) falls clearly inside the flagged region, and validated against the evaluation set below. They are meant to be legible and adjustable, not treated as fixed physical constants.

Key thresholds:
- `STRUCTURAL_WRAPPER_THRESHOLD = 0.35`
- `TRANSFORMATION_WRAPPER_THRESHOLD = 0.30`
- `HOUSEKEEPING_DISCOUNT_RATE = 0.75` (housekeeping statements count for only 25% of their raw weight)

## Key Metrics & Evaluation
Evaluated against `backend/tests/eval_set/` (9 genuine examples, 10 wrapper examples — including deliberately tricky cases on both sides: validation-padded wrappers, multi-return branches, no-op default guards, and genuine functions that call an API and then do real arithmetic/extraction/aggregation work):

| Metric | Value |
|---|---|
| Precision | 1.00 |
| Recall | 1.00 |
| F1 | 1.00 |

(Run `pytest tests/test_scoring.py -v -s` from `backend/` to reproduce; the test also asserts precision/recall/F1 each stay ≥ 0.80 as a regression floor, not the observed value, so the suite doesn't become brittle as the eval set grows.)

## Known Limitations
These follow directly from the "narrow tracing, not full symbolic execution" principle in `implementation-spec.md`:

- **Dynamic imports or aliased runtime dispatch** (`importlib.import_module(...)`, `getattr(module, name)()`) cannot be statically resolved and are classified `unknown`, never guessed as third-party.
- **Mutation-based data flow is not traced.** `merged = {}`; `merged.update(api.call(x))`; `return merged` will not be recognized as a same-key merge, because `.update()` mutates in place rather than rebinding the name — only reassignment chains are backward-traced. This is a deliberate scope boundary, not an oversight (full mutation/alias analysis would require real data-flow analysis, not narrow tracing).
- **Flow-insensitive taint for "external object" detection.** The taint set used to recognize `response.json()`-style method calls on a third-party result does not model reassignment invalidation with full precision; branchy reassignment of the same name to unrelated values is a known edge case.
- **`transformation_computed: false` functions are intentionally never flagged**, even when they look highly wrapper-like structurally — per spec, unknown transformation must fail safe rather than risk a false positive. This trades some recall for precision by design.
- **Candidacy requires a statically-attributable *direct* call.** A function whose only third-party interaction happens through a passed-in dependency-injected object (`self.client.get(...)` where `client` is a constructor parameter, not created from an import in this function) will not be picked up unless it can be traced back to an import; this is intentional conservatism, not a bug.

## Architecture Reference
See `implementation-spec.md` for the pipeline diagram and `API_CONTRACT.md` for the exact request/response schema. All scoring logic lives in `backend/engine/`; `backend/main.py` only orchestrates.
