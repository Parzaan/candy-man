"""
Step 1: Candidacy Filtering
============================
A function becomes a *candidate* for the rest of the pipeline only if it
contains at least one statically-attributable **direct** third-party call
somewhere in its own scope (not inside a nested def, which is scored as its
own separate candidate).

"Direct" and "statically-attributable" matter here: we only count calls whose
callable can be traced back, through this file's import statements, to a
non-stdlib, non-local module (see classifier.py). We deliberately do NOT
follow variable taint here (e.g. `resp = requests.get(x); resp.json()` --
`resp.json()` is not counted as a *candidacy* call), because candidacy is a
strict, conservative gate: it should never manufacture a candidate out of an
unresolved guess. Taint-based "external surface" tracking belongs to
structural.py, which needs the broader picture to weigh W_external.

No scoring happens in this module -- only detection + evidence collection.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Optional

from .classifier import (
    THIRD_PARTY,
    ImportRegistry,
    build_import_registry,
    classify_call,
    iter_own_scope,
    root_name_of,
)
from .repo_loader import ParsedFile


@dataclass
class ExternalCallSite:
    line: int
    module: str
    attr: Optional[str]  # the attribute called, e.g. "get" in requests.get(...); None for bare module() calls


@dataclass
class FunctionCandidate:
    name: str
    qualname: str
    file: str
    def_line: int
    node: ast.AST                 # ast.FunctionDef | ast.AsyncFunctionDef
    source: str                   # full source of the file, for downstream line-based evidence
    import_registry: ImportRegistry
    local_top_level: set
    external_calls: List[ExternalCallSite] = field(default_factory=list)
    candidate_reason: str = ""


def _qualname(stack: List[str], name: str) -> str:
    return ".".join(stack + [name]) if stack else name


def _find_functions(body, class_stack: List[str], out: List[tuple]):
    """Recursively find every FunctionDef/AsyncFunctionDef in the file,
    including methods nested in classes and functions nested in functions
    (each is its own independent candidate). `out` accumulates
    (qualname, node) pairs.
    """
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = _qualname(class_stack, node.name)
            out.append((qualname, node))
            # Functions nested inside this function are independent candidates too.
            _find_functions(node.body, class_stack + [node.name], out)
        elif isinstance(node, ast.ClassDef):
            _find_functions(node.body, class_stack + [node.name], out)
        # Note: we do not descend into other statement kinds here (If/For/...)
        # at module level scanning for defs, since Python does not allow
        # function/class defs to meaningfully hide inside expressions the
        # AST walk above would miss; nested defs found via ast.walk below
        # would double count, so we keep this restricted to body lists.


def _direct_third_party_calls(func_node, registry: ImportRegistry) -> List[ExternalCallSite]:
    calls = []
    for node in iter_own_scope(func_node.body):
        if not isinstance(node, ast.Call):
            continue
        classification = classify_call(node, registry)
        if classification != THIRD_PARTY:
            continue
        func = node.func
        if isinstance(func, ast.Name):
            module = registry.resolve(func.id).module or func.id
            attr = None
        elif isinstance(func, ast.Attribute):
            root = root_name_of(func)
            module = registry.resolve(root).module or root
            attr = func.attr
        else:
            continue
        calls.append(ExternalCallSite(line=node.lineno, module=module, attr=attr))
    # Deterministic ordering for reproducible evidence lists.
    calls.sort(key=lambda c: c.line)
    return calls


def extract_candidate_functions(parsed_files: List[ParsedFile], local_top_level: set) -> List[FunctionCandidate]:
    """Walks ASTs of parsed files and returns every function/method that
    qualifies as a Step 1 candidate (>=1 direct third-party call).

    Also implicitly gives us `total_functions_scanned` = the count of every
    FunctionDef/AsyncFunctionDef found, regardless of candidacy -- callers
    should count `all_functions` separately if they need that number; this
    function only returns candidates. See main.py orchestration.
    """
    candidates: List[FunctionCandidate] = []
    for pf in parsed_files:
        registry = build_import_registry(pf.tree, local_top_level)
        found: List[tuple] = []
        _find_functions(pf.tree.body, [], found)
        for qualname, node in found:
            external_calls = _direct_third_party_calls(node, registry)
            if not external_calls:
                continue
            first = external_calls[0]
            reason = (
                f"Direct call to third-party module '{first.module}'"
                + (f".{first.attr}" if first.attr else "")
                + f" at line {first.line}"
            )
            candidates.append(
                FunctionCandidate(
                    name=node.name,
                    qualname=qualname,
                    file=pf.relative_path,
                    def_line=node.lineno,
                    node=node,
                    source=pf.source,
                    import_registry=registry,
                    local_top_level=local_top_level,
                    external_calls=external_calls,
                    candidate_reason=reason,
                )
            )
    return candidates


def count_all_functions(parsed_files: List[ParsedFile]) -> int:
    """Every function found across all successfully-parsed files, matching
    API_CONTRACT.md's `total_functions_scanned` definition (independent of
    candidacy)."""
    total = 0
    for pf in parsed_files:
        found: List[tuple] = []
        _find_functions(pf.tree.body, [], found)
        total += len(found)
    return total
