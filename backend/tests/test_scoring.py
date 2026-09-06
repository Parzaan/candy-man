"""
Test Scoring Pipeline & Precision/Recall evaluation against eval_set.

Also covers the specific correctness properties the spec calls out
explicitly: transformation-unknown must never be treated as zero, malformed
files must never crash a scan, local/stdlib calls must never be classified
as third-party, the AND-gate must require both signals, and ranking must be
deterministic.
"""
import ast
import tempfile
from pathlib import Path

import pytest

from engine.candidacy import extract_candidate_functions
from engine.classifier import classify_module
from engine.repo_loader import ParsedFile, load_repository
from engine.scorer import rank_and_format_results
from engine.structural import compute_structural_score
from engine.transformation import compute_transformation_score

from .eval_set.genuine_examples import GENUINE_EXAMPLES
from .eval_set.wrapper_examples import WRAPPER_EXAMPLES


def analyze_snippet(source: str, target_qualname: str) -> dict:
    """Runs Step 1 -> Step 5 on a single in-memory source snippet and reports
    whether the target function ended up in `flagged`."""
    tree = ast.parse(source)
    parsed_file = ParsedFile(
        relative_path="snippet.py", absolute_path="snippet.py", source=source, tree=tree
    )
    candidates = extract_candidate_functions([parsed_file], local_top_level=set())
    match = next((c for c in candidates if c.qualname == target_qualname), None)
    if match is None:
        return {"is_candidate": False, "flagged": False}

    structural_result = compute_structural_score(match)
    transformation_result = compute_transformation_score(match)
    evidence_lines = sorted(
        set(structural_result["evidence_lines"]) | set(transformation_result["evidence_lines"])
    )
    scored = [
        {
            "function_name": match.qualname,
            "file": match.file,
            "def_line": match.def_line,
            "evidence_lines": evidence_lines,
            "r_structural": structural_result["r_structural"],
            "transformation_score": transformation_result["transformation_score"],
            "transformation_computed": transformation_result["transformation_computed"],
        }
    ]
    response = rank_and_format_results(repo="snippet", total_scanned=1, candidates=scored, unscannable_files=[])
    flagged_names = {item["function_name"] for item in response["flagged"]}
    return {
        "is_candidate": True,
        "flagged": match.qualname in flagged_names,
        "r_structural": structural_result["r_structural"],
        "transformation_score": transformation_result["transformation_score"],
        "transformation_computed": transformation_result["transformation_computed"],
    }


def test_pipeline_precision_recall():
    """Evaluates the detector pipeline against eval_set and asserts
    precision/recall/F1 for detecting wrapper functions (the positive class)
    stay above a reasonable bar. This is a review-priority triage tool, not a
    perfect classifier, but it should not be flooded with false positives on
    genuine tricky cases nor miss the obvious wrappers."""
    true_positives = 0   # wrapper, correctly flagged
    false_negatives = 0  # wrapper, missed
    true_negatives = 0   # genuine, correctly not flagged
    false_positives = 0  # genuine, incorrectly flagged

    fp_names = []
    fn_names = []

    for example in WRAPPER_EXAMPLES:
        result = analyze_snippet(example["source"], example["target"])
        if result["flagged"]:
            true_positives += 1
        else:
            false_negatives += 1
            fn_names.append(example["name"])

    for example in GENUINE_EXAMPLES:
        result = analyze_snippet(example["source"], example["target"])
        if result["flagged"]:
            false_positives += 1
            fp_names.append(example["name"])
        else:
            true_negatives += 1

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    print(
        f"\nprecision={precision:.2f} recall={recall:.2f} f1={f1:.2f} "
        f"(TP={true_positives} FP={false_positives} TN={true_negatives} FN={false_negatives})"
    )
    if fp_names:
        print("False positives (genuine examples incorrectly flagged):", fp_names)
    if fn_names:
        print("False negatives (wrapper examples missed):", fn_names)

    assert precision >= 0.8, f"Precision too low: {precision:.2f}, false positives: {fp_names}"
    assert recall >= 0.8, f"Recall too low: {recall:.2f}, false negatives: {fn_names}"
    assert f1 >= 0.8


@pytest.mark.parametrize("example", WRAPPER_EXAMPLES, ids=[e["name"] for e in WRAPPER_EXAMPLES])
def test_each_wrapper_example_is_a_candidate(example):
    """Sanity check independent of scoring: every wrapper example must at
    least pass Step 1 candidacy (it does contain a direct third-party call)."""
    result = analyze_snippet(example["source"], example["target"])
    assert result["is_candidate"], f"{example['name']} was not even considered a candidate"


def test_transformation_unknown_is_never_treated_as_zero_and_never_flagged():
    """A return pattern narrow backward-tracing cannot classify (here: a
    lambda capturing the external result) must yield transformation_computed
    = False, and such a function must NEVER appear in `flagged` even though
    it also has a very low R_structural."""
    source = '''
import requests

def get_lazy_loader(url):
    response = requests.get(url)
    return lambda: response
'''
    result = analyze_snippet(source, "get_lazy_loader")
    assert result["is_candidate"]
    # The lambda return pattern is outside narrow tracing's scope -- it must
    # bail out to "unknown", never to a confident score of 0.
    assert result["transformation_computed"] is False
    # And the AND-gate must never flag on an unknown transformation signal,
    # regardless of how low R_structural looks on its own.
    assert result["flagged"] is False


def test_malformed_file_does_not_crash_scan(tmp_path):
    """A single unparsable .py file must be recorded as unscannable and must
    never abort the rest of the repository scan."""
    good = tmp_path / "good.py"
    good.write_text(
        "import requests\n\n"
        "def get_thing(x):\n"
        "    return requests.get(x)\n"
    )
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    this is not python\n")

    loaded = load_repository(str(tmp_path), "local")
    try:
        assert "bad.py" in loaded.unscannable_files
        assert any(pf.relative_path == "good.py" for pf in loaded.parsed_files)
    finally:
        loaded.cleanup()


def test_no_python_files_found_raises_contract_error(tmp_path):
    from engine.repo_loader import RepoLoadError

    (tmp_path / "notes.txt").write_text("nothing python here")
    with pytest.raises(RepoLoadError) as exc_info:
        load_repository(str(tmp_path), "local")
    assert exc_info.value.code == "no_python_files_found"


def test_local_functions_are_not_classified_as_third_party(tmp_path):
    """A call into another module of the same repository must never be
    counted toward candidacy, even though it is imported via `from ... import`."""
    (tmp_path / "helpers.py").write_text("def helper(x):\n    return x * 2\n")
    (tmp_path / "main_mod.py").write_text(
        "from helpers import helper\n\n"
        "def compute(x):\n"
        "    return helper(x)\n"
    )
    loaded = load_repository(str(tmp_path), "local")
    try:
        candidates = extract_candidate_functions(loaded.parsed_files, loaded.local_top_level)
        assert not any(c.qualname == "compute" for c in candidates)
        assert classify_module("helpers", loaded.local_top_level) == "local"
    finally:
        loaded.cleanup()


def test_stdlib_calls_are_not_classified_as_third_party(tmp_path):
    (tmp_path / "mod.py").write_text(
        "import json\n\n"
        "def to_json(payload):\n"
        "    return json.dumps(payload)\n"
    )
    loaded = load_repository(str(tmp_path), "local")
    try:
        candidates = extract_candidate_functions(loaded.parsed_files, loaded.local_top_level)
        assert not any(c.qualname == "to_json" for c in candidates)
        assert classify_module("json", loaded.local_top_level) == "stdlib"
    finally:
        loaded.cleanup()


def test_and_gate_requires_both_signals_low_structural_alone_is_not_enough():
    """High transformation_score (genuine computation) must prevent a flag
    even when R_structural is low."""
    source = '''
import requests

def score_only_math(x):
    return requests.get("/rate").json()["rate"] * x + 1000000
'''
    # Deliberately huge internal-looking arithmetic constant is irrelevant --
    # what matters is that the return performs real arithmetic on the
    # extracted field, so transformation_score should be high.
    result = analyze_snippet(source, "score_only_math")
    assert result["is_candidate"]
    assert result["transformation_computed"] is True
    assert result["transformation_score"] > 0.30, "arithmetic on extracted field should score above the wrapper threshold"
    assert result["flagged"] is False


def test_and_gate_requires_both_signals_low_transformation_alone_is_not_enough():
    """A function with real internal branching/logic around the call, whose
    return happens to be a bare passthrough on one path, should not be
    flagged purely because transformation_score is low if R_structural shows
    substantial original logic."""
    source = '''
import requests

def process_and_cache(cache, key, url):
    if key in cache:
        return cache[key]
    for attempt in range(3):
        try:
            response = requests.get(url)
            break
        except Exception:
            continue
    else:
        raise RuntimeError("all attempts failed")
    cache[key] = response
    return response
'''
    result = analyze_snippet(source, "process_and_cache")
    assert result["is_candidate"]
    assert result["r_structural"] > 0.35, "retry loop + cache logic should register as substantial internal logic"
    assert result["flagged"] is False


def test_ranking_is_deterministic():
    scored = [
        {
            "function_name": "b_func",
            "file": "b.py",
            "def_line": 10,
            "evidence_lines": [10],
            "r_structural": 0.1,
            "transformation_score": 0.1,
            "transformation_computed": True,
        },
        {
            "function_name": "a_func",
            "file": "a.py",
            "def_line": 5,
            "evidence_lines": [5],
            "r_structural": 0.05,
            "transformation_score": 0.05,
            "transformation_computed": True,
        },
        {
            "function_name": "c_func",
            "file": "c.py",
            "def_line": 1,
            "evidence_lines": [1],
            "r_structural": 0.2,
            "transformation_score": 0.2,
            "transformation_computed": True,
        },
    ]
    result_1 = rank_and_format_results("repo", 3, scored, [])
    result_2 = rank_and_format_results("repo", 3, list(reversed(scored)), [])
    order_1 = [f["function_name"] for f in result_1["flagged"]]
    order_2 = [f["function_name"] for f in result_2["flagged"]]
    assert order_1 == order_2 == ["a_func", "b_func", "c_func"]
    assert [f["suspicion_rank"] for f in result_1["flagged"]] == [1, 2, 3]
