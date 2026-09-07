"""
Canary Check -- run this before every commit.
================================================
pytest checks final flagged/not-flagged verdicts, which can stay "correct"
even when the underlying numbers are wrong (this exact thing happened: a
regressed structural.py gave 0.3333 instead of 0.0, and 0.3816 instead of
0.5152 -- both wrong, but both still landed on the correct side of the
0.35 threshold, so the normal test suite passed anyway). This script checks
EXACT values for a few known-tricky functions, catching that class of bug
even when it doesn't flip a final verdict.

Run: python canary_check.py
Exit code 0 = all exact, non-zero = something drifted -- investigate before
committing, even if pytest is green.
"""
import ast
import sys

sys.path.insert(0, ".")
from engine.candidacy import extract_candidate_functions
from engine.repo_loader import ParsedFile
from engine.structural import compute_structural_score
from engine.transformation import compute_transformation_score

TOLERANCE = 0.0005

CANARIES = [
    {
        "name": "get_shipping_quote",
        "source": '''
import requests

def get_shipping_quote(order_id, api_key):
    response = requests.get(
        f"/quotes/{order_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    data = response.json()
    return {
        "rate": data["rate"],
        "carrier": data["carrier_name"],
    }
''',
        "expected_r": 0.0,
        "expected_t": 0.4,
    },
    {
        "name": "process_and_cache",
        "source": '''
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
''',
        "expected_r": 0.5152,
        "expected_t": 0.0,
    },
    {
        "name": "train_and_predict",
        "source": '''
import sklearn.linear_model

def train_and_predict(X_train, y_train, features):
    model = sklearn.linear_model.LinearRegression()
    model.fit(X_train, y_train)
    return model.predict(features)
''',
        "expected_r": None,  # not even a candidate
    },
]


def run():
    failures = []
    for canary in CANARIES:
        tree = ast.parse(canary["source"])
        pf = ParsedFile(relative_path="canary.py", absolute_path="canary.py", source=canary["source"], tree=tree)
        candidates = extract_candidate_functions([pf], local_top_level=set())
        match = next((c for c in candidates if c.qualname == canary["name"]), None)

        if canary["expected_r"] is None:
            if match is not None:
                failures.append(f"{canary['name']}: expected NOT a candidate, but it is one")
            else:
                print(f"OK  {canary['name']}: correctly not a candidate")
            continue

        if match is None:
            failures.append(f"{canary['name']}: expected a candidate, but got none")
            continue

        r = compute_structural_score(match)["r_structural"]
        t = compute_transformation_score(match)["transformation_score"]

        if abs(r - canary["expected_r"]) > TOLERANCE:
            failures.append(f"{canary['name']}: r_structural = {r} (expected {canary['expected_r']})")
        if abs(t - canary["expected_t"]) > TOLERANCE:
            failures.append(f"{canary['name']}: transformation_score = {t} (expected {canary['expected_t']})")
        if not failures or canary["name"] not in failures[-1]:
            print(f"OK  {canary['name']}: r={r}, t={t}")

    if failures:
        print("\nCANARY FAILURES -- do not commit until resolved:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll canaries exact. Safe to proceed.")


if __name__ == "__main__":
    run()