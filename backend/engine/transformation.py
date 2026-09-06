"""
Step 3 & 3.5: Data Transformation Analysis
=============================================
Determines whether a candidate function's return value reflects genuine
computation performed *on* a third-party call's result, or whether the
result is simply forwarded (a "thin wrapper" signal).

This module deliberately does NOT attempt full symbolic execution. It
implements a narrow, line-ordered backward trace: to classify `return name`,
it looks at the single most recent assignment to `name` earlier in the same
function, classifies *that* assignment's right-hand side, and recurses (up to
a small depth limit) until it either bottoms out at a direct external call
(base case: raw/passthrough), an expression unrelated to any external call
(base case: unrelated), or something too complex to classify confidently
(bails out -> `transformation_computed = False`).

Per API_CONTRACT.md: `transformation_computed = False` must NEVER be treated
as a score of 0 -- it means "we don't know", and scorer.py must never flag a
function on that basis. This module fails safe by construction: any
ambiguity anywhere in a return's trace makes the whole function's
transformation score unknown rather than guessing low.

Score scale (0.0 = definite passthrough/no computation, 1.0 = maximal):
these constants are this implementation's calibrated defaults -- the
provided implementation-spec.md names the required cases (passthrough,
extraction, arithmetic/string, same-key merge, no-op) but not their exact
numeric values.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional

from .candidacy import FunctionCandidate
from .classifier import (
    THIRD_PARTY,
    ImportRegistry,
    build_taint_set,
    classify_call,
    is_method_on_tainted,
    iter_own_scope,
)

# --- Calibrated transformation-case scores ----------------------------------
PASSTHROUGH_SCORE = 0.0          # `return api.call(x)` / `return result` (raw alias)
NO_OP_SCORE = 0.05               # `return result or {}` / `return x if x else x` -- cosmetic only
EXTRACTION_SCORE = 0.4           # `return result["key"]` / `return result.attr` -- shallow pull
SAME_KEY_MERGE_SCORE = 0.45      # `return {**base, **result}` -- structural combination, little logic
ARITHMETIC_STRING_SCORE = 0.75   # `return result + 10` / f-strings built from the result
GENERIC_TRANSFORM_SCORE = 0.7    # any other expression that clearly computes from the result

MAX_TRACE_DEPTH = 6


@dataclass
class _Trace:
    score: float
    computed: bool
    touches_external: bool  # False means this sub-expression is unrelated to any external call


_UNKNOWN = _Trace(0.0, False, False)


def _is_trivial_default(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict):
        return len(node.keys) == 0
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return len(node.elts) == 0
    return False


def _find_last_assignment(name: str, before_line: int, func_body) -> Optional[ast.Assign]:
    candidates = [
        n
        for n in iter_own_scope(func_body)
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == name
        and n.lineno < before_line
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda n: n.lineno)


def _trace_name(name: str, before_line: int, func_node, registry: ImportRegistry, tainted, depth: int) -> _Trace:
    assign = _find_last_assignment(name, before_line, func_node.body)
    if assign is None:
        # No assignment found in this scope before this point -- most likely
        # a function parameter, or a name assigned only via a construct we
        # don't trace (e.g. inside a `with ... as name`). We can state with
        # confidence that nothing here is derived from an external call.
        return _Trace(0.0, True, False)
    return _classify_expr(assign.value, assign.lineno, func_node, registry, tainted, depth + 1)


def _classify_no_op(expr: ast.AST, before_line: int, func_node, registry, tainted, depth: int) -> Optional[_Trace]:
    """Guards against pseudo-transformations that only add a default-value
    fallback or an identity ternary around an otherwise untouched external
    result -- these still read as "just returning the result" and must not
    be scored as if real computation happened."""
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or) and len(expr.values) == 2:
        left, right = expr.values
        if _is_trivial_default(right):
            trace = _classify_expr(left, before_line, func_node, registry, tainted, depth + 1)
            if trace.computed and trace.touches_external:
                return _Trace(NO_OP_SCORE, True, True)
    if isinstance(expr, ast.IfExp):
        same_branches = ast.dump(expr.body) == ast.dump(expr.orelse)
        if same_branches:
            trace = _classify_expr(expr.body, before_line, func_node, registry, tainted, depth + 1)
            if trace.computed and trace.touches_external:
                return _Trace(NO_OP_SCORE, True, True)
        elif _is_trivial_default(expr.orelse):
            trace = _classify_expr(expr.body, before_line, func_node, registry, tainted, depth + 1)
            if trace.computed and trace.touches_external:
                return _Trace(NO_OP_SCORE, True, True)
        elif _is_trivial_default(expr.body):
            trace = _classify_expr(expr.orelse, before_line, func_node, registry, tainted, depth + 1)
            if trace.computed and trace.touches_external:
                return _Trace(NO_OP_SCORE, True, True)
    return None


def _combine(sub_traces: List[_Trace], score_if_touched: float) -> _Trace:
    if any(not t.computed for t in sub_traces):
        return _UNKNOWN
    touched = any(t.touches_external for t in sub_traces)
    if not touched:
        return _Trace(0.0, True, False)
    return _Trace(score_if_touched, True, True)


def _classify_expr(expr: ast.AST, before_line: int, func_node, registry: ImportRegistry, tainted, depth: int) -> _Trace:
    if depth > MAX_TRACE_DEPTH:
        return _UNKNOWN

    # Case: direct third-party call -- the raw external result itself.
    if isinstance(expr, ast.Call) and classify_call(expr, registry) == THIRD_PARTY:
        return _Trace(PASSTHROUGH_SCORE, True, True)

    # Case: a further method call on an object we know came from a
    # third-party call (e.g. `response.json()`) -- still "the delegated
    # result", not yet a transformation of extracted data.
    if isinstance(expr, ast.Call) and is_method_on_tainted(expr, tainted):
        return _Trace(PASSTHROUGH_SCORE, True, True)

    # Case: a method call chained directly onto another call with no
    # intermediate variable (e.g. `requests.get(x).json()`) -- recurse into
    # the base call to see if the chain touches an external result at all.
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Call):
        base = _classify_expr(expr.func.value, before_line, func_node, registry, tainted, depth + 1)
        if base.computed and base.touches_external:
            return _Trace(PASSTHROUGH_SCORE, True, True)

    # Case: a bare variable reference -- narrow backward trace to its most
    # recent assignment. Always re-derived from line position (never trusts a
    # flow-insensitive taint set here) so reassignment/transformation after
    # the initial external capture is picked up correctly.
    if isinstance(expr, ast.Name):
        return _trace_name(expr.id, before_line, func_node, registry, tainted, depth)

    # Case: no-op guard (checked before generic BoolOp/IfExp handling below).
    if isinstance(expr, (ast.BoolOp, ast.IfExp)):
        no_op = _classify_no_op(expr, before_line, func_node, registry, tainted, depth)
        if no_op is not None:
            return no_op

    # Case: extraction -- subscript or attribute access on something that
    # touches an external result (`result["key"]`, `result.attr`).
    if isinstance(expr, (ast.Subscript, ast.Attribute)):
        base = _classify_expr(expr.value, before_line, func_node, registry, tainted, depth + 1)
        if not base.computed:
            return _UNKNOWN
        if base.touches_external:
            return _Trace(max(EXTRACTION_SCORE, base.score), True, True)
        return _Trace(0.0, True, False)

    # Case: arithmetic / comparison.
    if isinstance(expr, ast.BinOp):
        return _combine(
            [_classify_expr(expr.left, before_line, func_node, registry, tainted, depth + 1),
             _classify_expr(expr.right, before_line, func_node, registry, tainted, depth + 1)],
            ARITHMETIC_STRING_SCORE,
        )
    if isinstance(expr, ast.Compare):
        operands = [expr.left, *expr.comparators]
        return _combine(
            [_classify_expr(o, before_line, func_node, registry, tainted, depth + 1) for o in operands],
            ARITHMETIC_STRING_SCORE,
        )

    # Case: boolean combination not caught by the no-op guard above.
    if isinstance(expr, ast.BoolOp):
        return _combine(
            [_classify_expr(v, before_line, func_node, registry, tainted, depth + 1) for v in expr.values],
            GENERIC_TRANSFORM_SCORE,
        )

    # Case: ternary not caught by the no-op guard above.
    if isinstance(expr, ast.IfExp):
        return _combine(
            [_classify_expr(expr.body, before_line, func_node, registry, tainted, depth + 1),
             _classify_expr(expr.orelse, before_line, func_node, registry, tainted, depth + 1)],
            GENERIC_TRANSFORM_SCORE,
        )

    # Case: f-strings built from the result -- string transformation.
    if isinstance(expr, ast.JoinedStr):
        sub_traces = [
            _classify_expr(v.value, before_line, func_node, registry, tainted, depth + 1)
            for v in expr.values
            if isinstance(v, ast.FormattedValue)
        ]
        if not sub_traces:
            return _Trace(0.0, True, False)
        return _combine(sub_traces, ARITHMETIC_STRING_SCORE)

    # Case: dict literal -- `{**base, **result}` (same-key merge) or a keyed
    # value built from the result (`{"name": result["name"]}`, extraction-tier).
    if isinstance(expr, ast.Dict):
        unpack_sources = [v for k, v in zip(expr.keys, expr.values) if k is None]
        keyed_values = [v for k, v in zip(expr.keys, expr.values) if k is not None]
        unpack_traces = [_classify_expr(v, before_line, func_node, registry, tainted, depth + 1) for v in unpack_sources]
        keyed_traces = [_classify_expr(v, before_line, func_node, registry, tainted, depth + 1) for v in keyed_values]
        all_traces = unpack_traces + keyed_traces
        if any(not t.computed for t in all_traces):
            return _UNKNOWN
        touched = any(t.touches_external for t in all_traces)
        if not touched:
            return _Trace(0.0, True, False)
        if unpack_traces and any(t.touches_external for t in unpack_traces):
            return _Trace(SAME_KEY_MERGE_SCORE, True, True)
        return _Trace(EXTRACTION_SCORE, True, True)

    # Case: list/tuple/set literal containing something derived from the result.
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return _combine(
            [_classify_expr(e, before_line, func_node, registry, tainted, depth + 1) for e in expr.elts],
            GENERIC_TRANSFORM_SCORE,
        )

    # Case: comprehensions -- inspect the iterable(s) and element expression.
    if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        sub_nodes = [g.iter for g in expr.generators]
        if isinstance(expr, ast.DictComp):
            sub_nodes += [expr.key, expr.value]
        else:
            sub_nodes += [expr.elt]
        return _combine(
            [_classify_expr(n, before_line, func_node, registry, tainted, depth + 1) for n in sub_nodes],
            GENERIC_TRANSFORM_SCORE,
        )

    # Case: a call to a local/stdlib function (str(), len(), a helper, ...)
    # -- generic transformation if any argument touches the external result.
    if isinstance(expr, ast.Call):
        args = list(expr.args) + [kw.value for kw in expr.keywords]
        if not args:
            return _Trace(0.0, True, False)
        return _combine(
            [_classify_expr(a, before_line, func_node, registry, tainted, depth + 1) for a in args],
            GENERIC_TRANSFORM_SCORE,
        )

    # Case: plain literal -- unrelated to any external call.
    if isinstance(expr, ast.Constant):
        return _Trace(0.0, True, False)

    # Unhandled construct (lambda, walrus, starred, yield, await, ...):
    # narrow tracing intentionally does not attempt these -- bail safely.
    return _UNKNOWN


def _direct_discarded_external_call(func_node, registry: ImportRegistry, tainted) -> Optional[int]:
    for node in iter_own_scope(func_node.body):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if classify_call(call, registry) == THIRD_PARTY or is_method_on_tainted(call, tainted):
                return node.lineno
    return None


def compute_transformation_score(candidate: FunctionCandidate) -> dict:
    """Computes transformation_score and transformation_computed for a
    candidate function, per Step 3 & 3.5.

    Returns a dict with `transformation_score` (float), `transformation_computed`
    (bool) and `evidence_lines` (the return statement lines that drove the
    result). Multiple return statements are combined with MAX aggregation:
    if *any* return path demonstrates genuine transformation, the function is
    not judged a thin wrapper on this signal, even if other paths are plain
    passthroughs.
    """
    func_node = candidate.node
    registry = candidate.import_registry
    tainted = build_taint_set(func_node.body, registry)

    returns = [n for n in iter_own_scope(func_node.body) if isinstance(n, ast.Return)]

    if not returns:
        discarded_line = _direct_discarded_external_call(func_node, registry, tainted)
        if discarded_line is not None:
            # Total forwarding with no captured/returned result at all: a
            # confidently-classified, maximally wrapper-like case.
            return {
                "transformation_score": PASSTHROUGH_SCORE,
                "transformation_computed": True,
                "evidence_lines": [discarded_line],
            }
        # The external call's result is captured but neither returned nor
        # obviously discarded (e.g. stored on self, passed elsewhere) --
        # genuinely ambiguous without deeper data-flow analysis.
        return {"transformation_score": 0.0, "transformation_computed": False, "evidence_lines": []}

    scores: List[float] = []
    evidence_lines = set()
    all_computed = True
    for ret in returns:
        evidence_lines.add(ret.lineno)
        if ret.value is None:
            scores.append(0.0)
            continue
        trace = _classify_expr(ret.value, ret.lineno, func_node, registry, tainted, depth=0)
        if not trace.computed:
            all_computed = False
            continue
        scores.append(trace.score)

    if not all_computed:
        return {
            "transformation_score": 0.0,
            "transformation_computed": False,
            "evidence_lines": sorted(evidence_lines),
        }

    final_score = max(scores) if scores else 0.0
    return {
        "transformation_score": round(final_score, 4),
        "transformation_computed": True,
        "evidence_lines": sorted(evidence_lines),
    }
