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


def _child_statement_lists(stmt):
    """Yield each direct list of statements nested inside `stmt` (if/for/
    while/try bodies, elif chains via orelse, except handlers), but never
    descend into a nested function/class -- those are separate scopes /
    separate candidates entirely."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    for field_name in ("body", "orelse", "finalbody"):
        val = getattr(stmt, field_name, None)
        if isinstance(val, list) and val and isinstance(val[0], ast.stmt):
            yield val
    for handler in getattr(stmt, "handlers", None) or []:
        yield handler.body


def _names_assigned_in_block(stmts):
    names = set()
    for stmt in stmts:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        for child_block in _child_statement_lists(stmt):
            names |= _names_assigned_in_block(child_block)
    return names


def _find_ambiguous_if(name, func_body):
    """Returns the if-statement responsible for `name` being assigned in
    both its body and orelse, or None if `name` is not branch-ambiguous
    anywhere in the function. Revised after further review: an earlier
    version of this check only detected ambiguity and bailed out entirely
    -- but bailing means 'never flagged' (per the AND-gate), and one layer
    of if/else (a computed value vs. a trivial fallback) is extremely
    common, ordinary code, not a rare edge case. Blanket bail-out was
    giving a free pass to an entire common category. Returning the actual
    If node lets the caller MERGE both branches' values instead, mirroring
    the existing multi-return max-aggregation design rather than refusing
    to look."""

    def walk(stmts):
        for stmt in stmts:
            if isinstance(stmt, ast.If) and stmt.orelse:
                body_names = _names_assigned_in_block(stmt.body)
                orelse_names = _names_assigned_in_block(stmt.orelse)
                if name in body_names and name in orelse_names:
                    return stmt
            for child_block in _child_statement_lists(stmt):
                found = walk(child_block)
                if found is not None:
                    return found
        return None

    return walk(func_body)


def _last_assignment_in_block(name, stmts):
    """Last direct assignment to `name` within this flat list of
    statements only (does not descend into nested control flow -- callers
    pass the specific block they mean)."""
    candidates = [
        s for s in stmts
        if isinstance(s, ast.Assign) and len(s.targets) == 1
        and isinstance(s.targets[0], ast.Name) and s.targets[0].id == name
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda n: n.lineno)


def _collect_branch_assignments(name, if_stmt):
    """For the if-statement causing `name`'s branch-ambiguity, collect the
    relevant assignment to `name` from each mutually exclusive branch,
    recursing through elif chains (Python represents `elif` as a nested If
    inside `orelse`). A branch that doesn't assign `name` at all is simply
    skipped -- its absence doesn't add new ambiguity here."""
    results = []

    body_assign = _last_assignment_in_block(name, if_stmt.body)
    if body_assign is not None:
        results.append(body_assign)

    if len(if_stmt.orelse) == 1 and isinstance(if_stmt.orelse[0], ast.If):
        results.extend(_collect_branch_assignments(name, if_stmt.orelse[0]))
    else:
        orelse_assign = _last_assignment_in_block(name, if_stmt.orelse)
        if orelse_assign is not None:
            results.append(orelse_assign)

    return results


def _combine_max(traces):
    """Like _combine, but takes the actual max SCORE across sub-traces
    (each of which may land in a different tier -- one branch passthrough,
    another fully derived) rather than assigning one fixed tier. Used for
    branch-merged values, mirroring the existing multi-return
    max-aggregation philosophy: if any reachable path shows real
    computation, that's evidence of real work, so favor it."""
    if any(not t.computed for t in traces):
        return _UNKNOWN
    touching = [t for t in traces if t.touches_external]
    if not touching:
        return _Trace(0.0, True, False)
    best = max(touching, key=lambda t: t.score)
    return _Trace(best.score, True, True)


def _trace_name(name, before_line, func_node, registry, tainted, depth):
    ambiguous_if = _find_ambiguous_if(name, func_node.body)
    if ambiguous_if is not None:
        branch_assigns = _collect_branch_assignments(name, ambiguous_if)
        if not branch_assigns:
            return _UNKNOWN
        traces = [
            _classify_expr(a.value, a.lineno, func_node, registry, tainted, depth + 1)
            for a in branch_assigns
        ]
        return _combine_max(traces)
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
        touching = [t for t in all_traces if t.touches_external]
        if not touching:
            return _Trace(0.0, True, False)
        # Fixed after review: previously capped every multi-field dict at a
        # flat tier regardless of what its fields actually contained, so
        # {"trust": response["score"] * 1.5} (genuine arithmetic) scored
        # identically to {"name": response["name"]} (plain extraction).
        # Now takes the best (most-derived) inner field's score, with the
        # existing floor preserved -- a dict construction is itself at
        # least some repackaging, even if every field were a bare alias.
        best_inner = max(t.score for t in touching)
        floor = SAME_KEY_MERGE_SCORE if (unpack_traces and any(t.touches_external for t in unpack_traces)) else EXTRACTION_SCORE
        return _Trace(max(floor, best_inner), True, True)

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