"""
Import and Call Classifier
===========================
Single source of truth for the "local / stdlib / third-party" distinction used
throughout the Candy-Man pipeline (candidacy.py, structural.py, transformation.py
all import from here so the definition of "third-party" can never drift between
modules).

Design notes
------------
A call is only ever classified as third-party when it can be *statically
attributed* to an import of a non-stdlib, non-local module. Anything that
cannot be resolved this way (calls on parameters, calls on results of
`getattr`, dynamically constructed callables, etc.) is classified as
"unknown" rather than guessed as third-party -- per spec, unresolved calls
must never be silently assumed to be third-party, since that would inflate
false positives.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

Classification = str  # one of: "local", "stdlib", "third_party", "unknown"

LOCAL = "local"
STDLIB = "stdlib"
THIRD_PARTY = "third_party"
UNKNOWN = "unknown"

# sys.stdlib_module_names is the authoritative list of standard-library top
# level module names on this interpreter (Python 3.10+). We also fold in
# `builtins` explicitly since built-in functions (len, print, isinstance...)
# are never imported and should never be mistaken for third-party calls.
_STDLIB_NAMES = set(sys.stdlib_module_names) | {"builtins", "__main__"}


def classify_module(module_name: Optional[str], local_top_level: set) -> Classification:
    """Classify a dotted module name (e.g. "requests.auth") as local/stdlib/third_party.

    `local_top_level` is the set of top-level package/module names that exist
    inside the scanned repository (computed once by repo_loader and threaded
    through the whole pipeline so every module makes the same call).
    """
    if not module_name:
        # Relative imports (`from . import x`) carry no absolute module name;
        # by definition they refer to a module inside the same package, i.e. local.
        return LOCAL

    top = module_name.split(".")[0]
    if top in local_top_level:
        return LOCAL
    if top in _STDLIB_NAMES:
        return STDLIB
    return THIRD_PARTY


@dataclass
class ImportBinding:
    """Where a name in local scope came from."""

    module: Optional[str]          # absolute dotted module the name was imported from
    imported_name: Optional[str]   # the original attribute name for `from x import y as z`
    classification: Classification
    is_module_import: bool         # True for `import x[.y]`, False for `from x import y`


@dataclass
class ImportRegistry:
    """Maps local names visible in a file/scope to where they were imported from."""

    bindings: Dict[str, ImportBinding] = field(default_factory=dict)

    def resolve(self, name: str) -> Optional[ImportBinding]:
        return self.bindings.get(name)


def build_import_registry(tree: ast.AST, local_top_level: set) -> ImportRegistry:
    """Scan the *module-level and nested* Import/ImportFrom statements of a
    parsed file and build a name -> ImportBinding map. We intentionally scan
    the whole file (not just module level) because imports can legally
    appear inside functions.
    """
    registry = ImportRegistry()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                classification = classify_module(alias.name, local_top_level)
                registry.bindings[local_name] = ImportBinding(
                    module=alias.name,
                    imported_name=None,
                    classification=classification,
                    is_module_import=True,
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import -> always local regardless of the (possibly
                # None) module name.
                module_name = None
                classification = LOCAL
            else:
                module_name = node.module
                classification = classify_module(module_name, local_top_level)
            for alias in node.names:
                local_name = alias.asname or alias.name
                registry.bindings[local_name] = ImportBinding(
                    module=module_name,
                    imported_name=alias.name,
                    classification=classification,
                    is_module_import=False,
                )
    return registry


def root_name_of(expr: ast.AST) -> Optional[str]:
    """Return the leftmost Name id of a dotted attribute/call chain, e.g.
    for `requests.Session().get` -> "requests"; for `foo.bar` -> "foo".
    Returns None when the chain does not bottom out in a bare Name (e.g. it
    starts with a call, subscript, or literal), since such chains cannot be
    statically attributed to an import.
    """
    node = expr
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        return None


def iter_own_scope(stmts) -> "list[ast.AST]":
    """Depth-first traversal over a list of statements that stays within the
    *lexical scope* they belong to: it descends into control-flow blocks
    (if/for/while/try/with) but does NOT descend into the body of a nested
    function/async function/class/lambda, since those introduce their own
    scope (and, in the case of def/async def, their own separate candidate
    function). The boundary node itself is still yielded so callers can
    detect "there is a nested function/class here" without walking into it.

    Shared by candidacy.py, structural.py and transformation.py so "what
    counts as part of this function" is defined exactly once.
    """
    results = []
    stack = list(stmts)
    while stack:
        node = stack.pop()
        results.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return results


def build_taint_set(func_body, registry: ImportRegistry) -> set:
    """Track which local names hold a *raw* third-party call result (or a
    plain alias of one), so downstream modules can credit further method
    calls on that object as external delegation.

    Deliberately single-hop and flow-insensitive: extracting a value out of a
    tainted object into a new variable (`data = response.json()`) does NOT
    propagate taint onto `data` -- that is now a plain value, and further
    work on it should be judged as ordinary logic, not more delegation. This
    keeps the classification narrow and shared identically by structural.py
    (which needs "is this call external-ish") and transformation.py (which
    needs "was this call's object ever the raw external result").
    """
    tainted: set = set()
    assigns = [n for n in iter_own_scope(func_body) if isinstance(n, ast.Assign)]
    assigns.sort(key=lambda n: n.lineno)
    for node in assigns:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        target = node.targets[0].id
        value = node.value
        if isinstance(value, ast.Call) and classify_call(value, registry) == THIRD_PARTY:
            tainted.add(target)
        elif isinstance(value, ast.Name) and value.id in tainted:
            tainted.add(target)
    return tainted


def is_method_on_tainted(call: ast.Call, tainted: set) -> bool:
    """True when `call` is a method call (`obj.method(...)`) whose root
    object name is in the taint set, e.g. `response.json()` after
    `response = requests.get(...)`."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    root = root_name_of(func)
    return root is not None and root in tainted


def classify_call(call: ast.Call, registry: ImportRegistry) -> Classification:
    """Classify a Call node as local/stdlib/third_party/unknown using only the
    file's import registry -- no variable-taint tracking here (that lives in
    structural.py, which needs a distinct, broader notion of "external").
    """
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
            # `root` isn't an imported name at all -- e.g. a local variable
            # holding the result of some earlier call (`s = requests.Session();
            # s.get(...)`). We deliberately do NOT guess third-party here:
            # unresolved calls must never be silently assumed to be external.
            return UNKNOWN
        # `binding.classification` already reflects the module the name came
        # from, however it was imported: `import stripe` -> stripe.Invoice
        # .retrieve(...) and `from stripe import Invoice` -> Invoice.retrieve(...)
        # are both statically attributable to the same third-party module and
        # must classify identically.
        return binding.classification
    return UNKNOWN
