"""
Step 4 & 5: AND-Gate & Product Ranking
=========================================
Combines the two independent Step 2/Step 3 signals into the final flagged
list. This module contains no AST logic -- it only consumes the
already-computed structural and transformation results for each candidate
and applies the gate + ranking rules from implementation-spec.md /
API_CONTRACT.md.

AND gate
--------
A function is flagged only when BOTH signals independently look
wrapper-like:
  - R_structural <= STRUCTURAL_WRAPPER_THRESHOLD (mostly delegation, little
    original internal logic), AND
  - transformation_score <= TRANSFORMATION_WRAPPER_THRESHOLD (the return
    value is a passthrough / no-op, not a genuine computation), AND
  - transformation_computed is True.

`transformation_computed = False` is never a "flag" and never a "pass" --
it removes the function from consideration entirely, per the explicit
API_CONTRACT.md rule that unknown/uncomputed transformation must fail safe
and never manufacture a false positive. A low R_structural alone is never
sufficient (spec: "never flag a function merely because its structural
score is low").

The exact numeric thresholds are this implementation's calibrated defaults
(implementation-spec.md specifies the AND-gate architecture but not the
cutoffs); they were chosen so the worked example in API_CONTRACT.md
(r_structural=0.18, transformation_score=0.12) falls clearly inside the
flagged region.

Ranking
-------
suspicion_score = r_structural * transformation_score. Both factors are in
[0, 1] and are lowest for the most wrapper-like functions, so the product is
also lowest for the most suspicious functions; `flagged` is sorted by this
product ascending and `suspicion_rank` is assigned 1..N accordingly (1 = most
suspicious). This is a deterministic review-priority ordering, not a
probability of wrongdoing -- a flag is a signal for a human reviewer, never
proof.
"""
from __future__ import annotations

from typing import Any, Dict, List

STRUCTURAL_WRAPPER_THRESHOLD = 0.35
TRANSFORMATION_WRAPPER_THRESHOLD = 0.30


def _passes_and_gate(candidate: Dict[str, Any]) -> bool:
    if not candidate.get("transformation_computed", False):
        return False
    if candidate["r_structural"] > STRUCTURAL_WRAPPER_THRESHOLD:
        return False
    if candidate["transformation_score"] > TRANSFORMATION_WRAPPER_THRESHOLD:
        return False
    return True


def _suspicion_score(candidate: Dict[str, Any]) -> float:
    return candidate["r_structural"] * candidate["transformation_score"]


def rank_and_format_results(
    repo: str,
    total_scanned: int,
    candidates: List[Dict[str, Any]],
    unscannable_files: List[str],
) -> Dict[str, Any]:
    """Filters candidates with the AND-gate, ranks the survivors, and builds
    the final ScanResponse dict.

    Each item in `candidates` is expected to carry:
      function_name, file, def_line, evidence_lines,
      r_structural, transformation_score, transformation_computed
    (assembled by main.py from structural.compute_structural_score +
    transformation.compute_transformation_score).
    """
    passing = [c for c in candidates if _passes_and_gate(c)]

    # Deterministic ordering: primary key is the suspicion product ascending
    # (lower product = more suspicious = better rank); ties are broken by
    # file path, then definition line, then function name so re-running the
    # scan on unchanged code always yields the same ranking.
    passing.sort(key=lambda c: (_suspicion_score(c), c["file"], c["def_line"], c["function_name"]))

    flagged = []
    for rank, candidate in enumerate(passing, start=1):
        flagged.append(
            {
                "function_name": candidate["function_name"],
                "file": candidate["file"],
                "def_line": candidate["def_line"],
                "evidence_lines": sorted(set(candidate.get("evidence_lines", []))),
                "r_structural": candidate["r_structural"],
                "transformation_score": candidate["transformation_score"],
                "transformation_computed": candidate["transformation_computed"],
                "suspicion_rank": rank,
            }
        )

    return {
        "repo": repo,
        "total_functions_scanned": total_scanned,
        "candidates_considered": len(candidates),
        "unscannable_files": unscannable_files,
        "flagged": flagged,
    }
