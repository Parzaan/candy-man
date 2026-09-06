from __future__ import annotations

import ast
from typing import List, Set

from .candidacy import FunctionCandidate
from .classifier import (
    THIRD_PARTY,
    ImportRegistry,
    build_taint_set,
    classify_call,
    is_method_on_tainted,
    iter_own_scope,
    root_name_of,
)

W_INTERNAL_STATEMENT = 1.0
W_INTERNAL_LOOP = 1.5
W_INTERNAL_BRANCH_DECISION = 0.5

W_EXTERNAL_CALL = 1.0
W_METHOD_ON_EXTERNAL = 1.0

HOUSEKEEPING_DISCOUNT_RATE = 0.75
W_HOUSEKEEPING_GUARD = 1.0
W_HOUSEKEEPING_TRY = 0.5
W_HOUSEKEEPING_WITH = 0.3
W_HOUSEKEEPING_ASSERT = 0.5
W_HOUSEKEEPING_RAISE = 0.3
W_HOUSEKEEPING_LOG_CALL = 0.3
W_HOUSEKEEPING_TRIVIAL = 0.2

_LOG_CALL_NAMES = {"print", "log", "debug", "info", "warn", "warning", "error", "exception", "critical"}


class _Weighted:
    __slots__ = ("weight", "line", "is_housekeeping")

    def __init__(self, weight, line, is_housekeeping):
        self.weight = weight
        self.line = line
        self.is_housekeeping = is_housekeeping


def _is_logging_call(call, registry):
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr in _LOG_CALL_NAMES:
            return True
        root = root_name_of(func)
        binding = registry.resolve(root) if root else None
        if binding and binding.module == "logging":
            return True
    elif isinstance(func, ast.Name):
        if func.id in _LOG_CALL_NAMES:
            return True
    return False


def _is_external_ish_call(call, registry, tainted):
    if classify_call(call, registry) == THIRD_PARTY:
        return True
    if is_method_on_tainted(call, tainted):
        return True
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call):
        return _is_external_ish_call(func.value, registry, tainted)
    return False


_MUTATION_METHODS = {"append", "extend", "add", "insert", "update", "push"}


def _is_pure_forwarding_mutation(call, registry, tainted):
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in _MUTATION_METHODS:
        return False
    args = list(call.args) + [kw.value for kw in call.keywords]
    if not args:
        return False
    return all(_is_pure_external_or_alias(a, registry, tainted) for a in args)


def _is_pure_external_or_alias(expr, registry, tainted):
    if isinstance(expr, ast.Call):
        return _is_external_ish_call(expr, registry, tainted)
    if isinstance(expr, ast.Name):
        return expr.id in tainted
    if isinstance(expr, ast.Dict):
        return all(_is_pure_external_or_alias(v, registry, tainted) for v in expr.values)
    if isinstance(expr, (ast.List, ast.Tuple)):
        return all(_is_pure_external_or_alias(e, registry, tainted) for e in expr.elts)
    if isinstance(expr, ast.Subscript):
        return _is_pure_external_or_alias(expr.value, registry, tainted)
    if isinstance(expr, ast.Attribute):
        return _is_pure_external_or_alias(expr.value, registry, tainted)
    return False


def _loop_has_internal_work(node, registry, tainted):
    for stmt in node.body:
        for item in _classify_top_level_node(stmt, registry, tainted):
            if item.weight > 0 and not item.is_housekeeping:
                return True
    return False


def _is_trivial_literal_or_rename(expr):
    if isinstance(expr, ast.Name):
        return True
    if isinstance(expr, ast.Constant):
        return True
    return False


def _is_simple_guard_test(test):
    def is_simple_atom(node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return is_simple_atom(node.operand)
        if isinstance(node, ast.Compare):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id in {"isinstance", "hasattr", "len", "callable"}
        return False

    if isinstance(test, ast.BoolOp):
        return all(is_simple_atom(v) for v in test.values)
    return is_simple_atom(test)


def _is_trivial_return_value(value):
    """A guard clause's return value only counts as 'exiting with nothing
    meaningful' if it's None (bare `return`), a Constant, or a bare Name --
    e.g. `return None`, `return []`, `return default`. A Return carrying a
    computed/extracted value (Subscript, Attribute, Call, or any other
    expression) is genuine conditional logic, not validation -- e.g. a
    cache-hit early return -- and must not be discounted as housekeeping."""
    if value is None:
        return True
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Name):
        return True
    return False


def _is_guard_clause(node):
    if node.orelse:
        return False
    if not _is_simple_guard_test(node.test):
        return False
    if not node.body or len(node.body) > 2:
        return False
    last = node.body[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.Return):
        return _is_trivial_return_value(last.value)
    return False


def _classify_top_level_node(node, registry, tainted):
    out = []
    line = getattr(node, "lineno", 0)

    if isinstance(node, ast.If):
        if _is_guard_clause(node):
            out.append(_Weighted(W_HOUSEKEEPING_GUARD, line, True))
        else:
            out.append(_Weighted(W_INTERNAL_BRANCH_DECISION, line, False))

    elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        if _loop_has_internal_work(node, registry, tainted):
            out.append(_Weighted(W_INTERNAL_LOOP, line, False))

    elif isinstance(node, (ast.Try,)):
        out.append(_Weighted(W_HOUSEKEEPING_TRY, line, True))

    elif isinstance(node, (ast.With, ast.AsyncWith)):
        out.append(_Weighted(W_HOUSEKEEPING_WITH, line, True))

    elif isinstance(node, ast.Assert):
        out.append(_Weighted(W_HOUSEKEEPING_ASSERT, line, True))

    elif isinstance(node, ast.Raise):
        out.append(_Weighted(W_HOUSEKEEPING_RAISE, line, True))

    elif isinstance(node, ast.Assign):
        if _is_pure_external_or_alias(node.value, registry, tainted):
            pass
        elif _is_trivial_literal_or_rename(node.value):
            out.append(_Weighted(W_HOUSEKEEPING_TRIVIAL, line, True))
        else:
            out.append(_Weighted(W_INTERNAL_STATEMENT, line, False))

    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        value = getattr(node, "value", None)
        if value is None:
            pass
        elif isinstance(node, ast.AnnAssign) and _is_pure_external_or_alias(value, registry, tainted):
            pass
        else:
            out.append(_Weighted(W_INTERNAL_STATEMENT, line, False))

    elif isinstance(node, ast.Return):
        value = node.value
        if value is not None and not (
            isinstance(value, ast.Name)
            or isinstance(value, ast.Constant)
            or _is_pure_external_or_alias(value, registry, tainted)
        ):
            out.append(_Weighted(W_INTERNAL_STATEMENT, line, False))

    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if _is_external_ish_call(call, registry, tainted):
            pass
        elif _is_pure_forwarding_mutation(call, registry, tainted):
            pass
        elif _is_logging_call(call, registry):
            out.append(_Weighted(W_HOUSEKEEPING_LOG_CALL, line, True))
        else:
            out.append(_Weighted(W_INTERNAL_STATEMENT, line, False))

    return out


def _collect_calls(func_node, registry, tainted):
    out = []
    for node in iter_own_scope(func_node.body):
        if not isinstance(node, ast.Call):
            continue
        line = node.lineno
        if classify_call(node, registry) == THIRD_PARTY:
            out.append(_Weighted(W_EXTERNAL_CALL, line, False))
        elif is_method_on_tainted(node, tainted) or _is_external_ish_call(node, registry, tainted):
            out.append(_Weighted(W_METHOD_ON_EXTERNAL, line, False))
    return out


_STATEMENT_NODE_TYPES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith,
    ast.Assert, ast.Raise, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Return, ast.Expr,
)


def compute_structural_score(candidate: FunctionCandidate) -> dict:
    func_node = candidate.node
    registry = candidate.import_registry
    tainted = build_taint_set(func_node.body, registry)

    evidence_lines: Set[int] = set()

    consumed_ids: Set[int] = set()
    for node in iter_own_scope(func_node.body):
        if isinstance(node, ast.If) and _is_guard_clause(node):
            for stmt in node.body:
                consumed_ids.add(id(stmt))

    external_weight = 0.0
    for item in _collect_calls(func_node, registry, tainted):
        external_weight += item.weight
        evidence_lines.add(item.line)

    internal_weight_full = 0.0
    housekeeping_weight_full = 0.0
    for node in iter_own_scope(func_node.body):
        if not isinstance(node, _STATEMENT_NODE_TYPES):
            continue
        if id(node) in consumed_ids:
            continue
        for item in _classify_top_level_node(node, registry, tainted):
            internal_weight_full += item.weight
            if item.is_housekeeping:
                housekeeping_weight_full += item.weight
                evidence_lines.add(item.line)

    denom_raw = internal_weight_full + external_weight
    raw_ratio = (internal_weight_full / denom_raw) if denom_raw > 0 else 0.0

    housekeeping_fraction = (
        housekeeping_weight_full / internal_weight_full if internal_weight_full > 0 else 0.0
    )
    discount_factor = 1.0 - (housekeeping_fraction * HOUSEKEEPING_DISCOUNT_RATE)
    r_structural = max(0.0, min(1.0, raw_ratio * discount_factor))

    for c in candidate.external_calls:
        evidence_lines.add(c.line)

    return {
        "r_structural": round(r_structural, 4),
        "evidence_lines": sorted(evidence_lines),
        "w_internal": round(internal_weight_full, 4),
        "w_external": round(external_weight, 4),
        "raw_ratio": round(raw_ratio, 4),
        "housekeeping_fraction": round(housekeeping_fraction, 4),
    }