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

PASSTHROUGH_SCORE = 0.0
NO_OP_SCORE = 0.05
EXTRACTION_SCORE = 0.4
SAME_KEY_MERGE_SCORE = 0.45
ARITHMETIC_STRING_SCORE = 0.75
GENERIC_TRANSFORM_SCORE = 0.7

MAX_TRACE_DEPTH = 8


@dataclass
class _Trace:
    score: float
    computed: bool
    touches_external: bool


_UNKNOWN = _Trace(0.0, False, False)


def _is_trivial_default(node):
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict):
        return len(node.keys) == 0
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return len(node.elts) == 0
    return False


def _find_last_assignment(name, before_line, func_body):
    candidates = [
        n for n in iter_own_scope(func_body)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name
        and n.lineno < before_line
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda n: n.lineno)


def _trace_name(name, before_line, func_node, registry, tainted, depth):
    assign = _find_last_assignment(name, before_line, func_node.body)
    if assign is None:
        return _Trace(0.0, True, False)
    return _classify_expr(assign.value, assign.lineno, func_node, registry, tainted, depth + 1)


def _classify_no_op(expr, before_line, func_node, registry, tainted, depth):
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


def _combine(sub_traces, score_if_touched):
    if any(not t.computed for t in sub_traces):
        return _UNKNOWN
    touched = any(t.touches_external for t in sub_traces)
    if not touched:
        return _Trace(0.0, True, False)
    return _Trace(score_if_touched, True, True)


def _classify_expr(expr, before_line, func_node, registry, tainted, depth):
    if depth > MAX_TRACE_DEPTH:
        return _UNKNOWN

    if isinstance(expr, ast.Call) and classify_call(expr, registry) == THIRD_PARTY:
        return _Trace(PASSTHROUGH_SCORE, True, True)

    if isinstance(expr, ast.Call) and is_method_on_tainted(expr, tainted):
        return _Trace(PASSTHROUGH_SCORE, True, True)

    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Call):
        base = _classify_expr(expr.func.value, before_line, func_node, registry, tainted, depth + 1)
        if not base.computed:
            # Fix (found via stress testing): the base trace ran out of
            # depth budget and returned _UNKNOWN. This previously fell
            # through to the generic "Call with no args" handler below,
            # which confidently returned "doesn't touch external" -- a
            # wrong, overconfident answer that caused genuine
            # external-derived computations to silently score as pure
            # passthrough whenever they were deep enough in a trace chain.
            # Must propagate the uncertainty instead.
            return _UNKNOWN
        if base.touches_external:
            return _Trace(PASSTHROUGH_SCORE, True, True)
        # base.computed is True but doesn't touch external -- correctly
        # fall through to the generic Call handler below.

    if isinstance(expr, ast.Name):
        return _trace_name(expr.id, before_line, func_node, registry, tainted, depth)

    if isinstance(expr, (ast.BoolOp, ast.IfExp)):
        no_op = _classify_no_op(expr, before_line, func_node, registry, tainted, depth)
        if no_op is not None:
            return no_op

    if isinstance(expr, (ast.Subscript, ast.Attribute)):
        base = _classify_expr(expr.value, before_line, func_node, registry, tainted, depth + 1)
        if not base.computed:
            return _UNKNOWN
        if base.touches_external:
            return _Trace(max(EXTRACTION_SCORE, base.score), True, True)
        return _Trace(0.0, True, False)

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

    if isinstance(expr, ast.BoolOp):
        return _combine(
            [_classify_expr(v, before_line, func_node, registry, tainted, depth + 1) for v in expr.values],
            GENERIC_TRANSFORM_SCORE,
        )

    if isinstance(expr, ast.IfExp):
        return _combine(
            [_classify_expr(expr.body, before_line, func_node, registry, tainted, depth + 1),
             _classify_expr(expr.orelse, before_line, func_node, registry, tainted, depth + 1)],
            GENERIC_TRANSFORM_SCORE,
        )

    if isinstance(expr, ast.JoinedStr):
        sub_traces = [
            _classify_expr(v.value, before_line, func_node, registry, tainted, depth + 1)
            for v in expr.values if isinstance(v, ast.FormattedValue)
        ]
        if not sub_traces:
            return _Trace(0.0, True, False)
        return _combine(sub_traces, ARITHMETIC_STRING_SCORE)

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

    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return _combine(
            [_classify_expr(e, before_line, func_node, registry, tainted, depth + 1) for e in expr.elts],
            GENERIC_TRANSFORM_SCORE,
        )

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

    if isinstance(expr, ast.Call):
        args = list(expr.args) + [kw.value for kw in expr.keywords]
        if not args:
            return _Trace(0.0, True, False)
        return _combine(
            [_classify_expr(a, before_line, func_node, registry, tainted, depth + 1) for a in args],
            GENERIC_TRANSFORM_SCORE,
        )

    if isinstance(expr, ast.Constant):
        return _Trace(0.0, True, False)

    return _UNKNOWN


def _direct_discarded_external_call(func_node, registry, tainted):
    for node in iter_own_scope(func_node.body):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if classify_call(call, registry) == THIRD_PARTY or is_method_on_tainted(call, tainted):
                return node.lineno
    return None


def compute_transformation_score(candidate: FunctionCandidate) -> dict:
    func_node = candidate.node
    registry = candidate.import_registry
    tainted = build_taint_set(func_node.body, registry)

    returns = [n for n in iter_own_scope(func_node.body) if isinstance(n, ast.Return)]

    if not returns:
        discarded_line = _direct_discarded_external_call(func_node, registry, tainted)
        if discarded_line is not None:
            return {
                "transformation_score": PASSTHROUGH_SCORE,
                "transformation_computed": True,
                "evidence_lines": [discarded_line],
            }
        return {"transformation_score": 0.0, "transformation_computed": False, "evidence_lines": []}

    scores = []
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
        return {"transformation_score": 0.0, "transformation_computed": False, "evidence_lines": sorted(evidence_lines)}

    final_score = max(scores) if scores else 0.0
    return {
        "transformation_score": round(final_score, 4),
        "transformation_computed": True,
        "evidence_lines": sorted(evidence_lines),
    }