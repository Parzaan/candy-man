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

Classification = str

LOCAL = "local"
STDLIB = "stdlib"
THIRD_PARTY = "third_party"
LOCAL_COMPUTE_LIB = "local_compute_lib"
UNKNOWN = "unknown"

_STDLIB_NAMES = set(sys.stdlib_module_names) | {"builtins", "__main__"}

# Curated, deliberately-scoped allowlist of well-known LOCAL, on-device
# computation libraries -- fixing a real false-positive class found during
# demo testing: a call to sklearn.LinearRegression().fit(...) was being
# scored identically to a call to requests.get(...), since both are
# "non-stdlib imports". That conflates two fundamentally different things:
# delegating work to a REMOTE third-party SERVICE you don't control
# (requests, stripe, openai, boto3, twilio -- genuine delegation, the thing
# this tool exists to catch) versus using a LOCAL library to run YOUR OWN
# computation on YOUR OWN machine (numpy, sklearn, torch -- normal
# engineering, no different in kind from using Python's own math module).
# A real train-then-predict ML function was scoring r_structural=0.0 AND
# transformation_score=0.0 (predict() on a "tainted" model object read as a
# passthrough, same as response.json()) -- i.e. flagged as a thin wrapper
# for doing genuine, substantial local computation. This allowlist routes
# these libraries to a distinct classification that (like STDLIB) is never
# treated as delegation anywhere downstream (candidacy, W_external,
# taint propagation, transformation scoring), without touching any other
# file's logic.
#
# Deliberately NOT solving: whether a model was trained locally vs loaded
# from a checkpoint (joblib.load(...), torch.load(...)) -- both are still
# local computation under this tool's own code, and the distinction doesn't
# change the verdict this tool cares about, so no `.fit()`/`.train()`
# heuristic is added. Also not solved, and stated as a limitation rather
# than chased: this list is necessarily incomplete -- a genuinely
# third-party local-compute library not on this list (a niche or newer ML
# framework) will still be misclassified as delegation-worthy.
_LOCAL_COMPUTE_LIBRARY_NAMES = {
    "numpy", "pandas", "scipy", "sklearn", "torch", "tensorflow", "keras",
    "jax", "cv2", "matplotlib", "seaborn", "plotly", "nltk", "spacy",
    "gensim", "statsmodels", "xgboost", "lightgbm", "catboost", "PIL",
    "skimage", "numba",
}


def classify_module(module_name, local_top_level):
    if not module_name:
        return LOCAL
    top = module_name.split(".")[0]
    if top in local_top_level:
        return LOCAL
    if top in _STDLIB_NAMES:
        return STDLIB
    if top in _LOCAL_COMPUTE_LIBRARY_NAMES:
        return LOCAL_COMPUTE_LIB
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