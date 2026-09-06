from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

Classification = str

LOCAL = "local"
STDLIB = "stdlib"
THIRD_PARTY = "third_party"
UNKNOWN = "unknown"

_STDLIB_NAMES = set(sys.stdlib_module_names) | {"builtins", "__main__"}


def classify_module(module_name, local_top_level):
    if not module_name:
        return LOCAL
    top = module_name.split(".")[0]
    if top in local_top_level:
        return LOCAL
    if top in _STDLIB_NAMES:
        return STDLIB
    return THIRD_PARTY


@dataclass
class ImportBinding:
    module: Optional[str]
    imported_name: Optional[str]
    classification: Classification
    is_module_import: bool


@dataclass
class ImportRegistry:
    bindings: Dict[str, ImportBinding] = field(default_factory=dict)

    def resolve(self, name):
        return self.bindings.get(name)


def build_import_registry(tree, local_top_level):
    registry = ImportRegistry()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                classification = classify_module(alias.name, local_top_level)
                registry.bindings[local_name] = ImportBinding(
                    module=alias.name, imported_name=None,
                    classification=classification, is_module_import=True,
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                module_name = None
                classification = LOCAL
            else:
                module_name = node.module
                classification = classify_module(module_name, local_top_level)
            for alias in node.names:
                local_name = alias.asname or alias.name
                registry.bindings[local_name] = ImportBinding(
                    module=module_name, imported_name=alias.name,
                    classification=classification, is_module_import=False,
                )
    return registry


def root_name_of(expr):
    node = expr
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        return None


def iter_own_scope(stmts):
    results = []
    stack = list(stmts)
    while stack:
        node = stack.pop()
        results.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return results


def build_taint_set(func_body, registry):
    """Fixed-point propagation (fix applied after review -- see below): a
    single forward pass previously missed `data = response.json()`-style
    assignments, since it only recognized (a) a direct third-party call, or
    (b) a bare alias of an already-tainted name. A method call on an
    already-tainted object (`.json()`, `.text`, any attribute/method access
    chained off a tainted variable) is already treated as "still the
    external result" everywhere else in this codebase (structural.py's
    _is_external_ish_call, is_method_on_tainted itself) -- this function was
    the one place that definition wasn't applied, which silently inflated
    W_internal for any function that captured a raw response into one
    variable and then called a method on it into a second variable before
    using the result (an extremely common real-world pattern: fetch, then
    `.json()`, then use). Iterating to a fixed point also correctly handles
    longer chains (`a = api.call(); b = a.json(); c = b.get("x")`, etc.)."""
    tainted = set()
    assigns = [n for n in iter_own_scope(func_body) if isinstance(n, ast.Assign)]
    assigns.sort(key=lambda n: n.lineno)

    changed = True
    while changed:
        changed = False
        for node in assigns:
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target = node.targets[0].id
            if target in tainted:
                continue
            value = node.value
            if isinstance(value, ast.Call) and classify_call(value, registry) == THIRD_PARTY:
                tainted.add(target)
                changed = True
            elif isinstance(value, ast.Name) and value.id in tainted:
                tainted.add(target)
                changed = True
            elif isinstance(value, ast.Call) and is_method_on_tainted(value, tainted):
                tainted.add(target)
                changed = True
    return tainted


def is_method_on_tainted(call, tainted):
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    root = root_name_of(func)
    return root is not None and root in tainted


def classify_call(call, registry):
    func = call.func
    if isinstance(func, ast.Name):
        binding = registry.resolve(func.id)
        if binding is None:
            return UNKNOWN
        return binding.classification
    if isinstance(func, ast.Attribute):
        root = root_name_of(func)
        if root is None:
            return UNKNOWN
        binding = registry.resolve(root)
        if binding is None:
            return UNKNOWN
        return binding.classification
    return UNKNOWN