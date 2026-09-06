GENUINE_EXAMPLES = [
    {
        "name": "arithmetic_after_call",
        "target": "total_price",
        "source": '''
import requests

def total_price(order_id):
    order = requests.get(f"/orders/{order_id}").json()
    subtotal = sum(item["price"] * item["qty"] for item in order["items"])
    tax = subtotal * 0.08
    return subtotal + tax
''',
    },
    {
        "name": "validation_then_real_computation",
        "target": "normalized_score",
        "source": '''
import requests

def normalized_score(user_id, max_score):
    if not user_id:
        raise ValueError("user_id required")
    if max_score <= 0:
        raise ValueError("max_score must be positive")
    profile = requests.get(f"/profiles/{user_id}").json()
    raw = profile["score"]
    clamped = max(0, min(raw, max_score))
    return round((clamped / max_score) * 100, 2)
''',
    },
    {
        "name": "extraction_followed_by_transformation",
        "target": "shipping_label",
        "source": '''
import requests

def shipping_label(address_id):
    address = requests.get(f"/addresses/{address_id}").json()
    street = address["street"].strip().title()
    city = address["city"].strip().title()
    postal = address["postal_code"].replace(" ", "").upper()
    return f"{street}\\n{city} {postal}"
''',
    },
    {
        "name": "multiple_calls_combined",
        "target": "account_summary",
        "source": '''
import requests

def account_summary(account_id):
    profile = requests.get(f"/accounts/{account_id}").json()
    transactions = requests.get(f"/accounts/{account_id}/transactions").json()
    total_spent = sum(t["amount"] for t in transactions if t["amount"] < 0)
    return {
        "name": profile["name"],
        "total_spent": abs(total_spent),
        "transaction_count": len(transactions),
    }
''',
    },
    {
        "name": "defensive_but_substantial",
        "target": "safe_average_rating",
        "source": '''
import requests

def safe_average_rating(product_id):
    if not isinstance(product_id, str):
        raise TypeError("product_id must be a string")
    try:
        reviews = requests.get(f"/products/{product_id}/reviews").json()
    except Exception as exc:
        raise RuntimeError("could not fetch reviews") from exc
    if not reviews:
        return 0.0
    scores = [r["rating"] for r in reviews if r.get("verified")]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)
''',
    },
    {
        "name": "loop_aggregation",
        "target": "top_selling_products",
        "source": '''
import requests

def top_selling_products(store_id, limit):
    products = requests.get(f"/stores/{store_id}/products").json()
    ranked = []
    for product in products:
        score = product["units_sold"] * product["price"]
        ranked.append((score, product["name"]))
    ranked.sort(reverse=True)
    return [name for _, name in ranked[:limit]]
''',
    },
    {
        "name": "string_report_building",
        "target": "build_status_report",
        "source": '''
import requests

def build_status_report(service_name):
    status = requests.get(f"/health/{service_name}").json()
    uptime_pct = round(status["uptime_seconds"] / status["total_seconds"] * 100, 1)
    lines = [f"Service: {service_name}", f"Uptime: {uptime_pct}%"]
    if status["errors"]:
        lines.append(f"Errors detected: {len(status['errors'])}")
    return "\\n".join(lines)
''',
    },
    {
        "name": "max_aggregation_branches_all_genuine",
        "target": "resolve_price",
        "source": '''
import requests

def resolve_price(sku, currency):
    quote = requests.get(f"/prices/{sku}").json()
    base = quote["amount"]
    if currency == "USD":
        return round(base, 2)
    elif currency == "EUR":
        return round(base * quote["eur_rate"], 2)
    else:
        return round(base * quote.get("other_rate", 1.0) * 1.02, 2)
''',
    },
    {
        "name": "stdlib_heavy_no_third_party",
        "target": "hash_and_encode",
        "source": '''
import hashlib
import json

def hash_and_encode(payload):
    serialized = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return {"payload": serialized, "digest": digest}
''',
    },
    {
        "name": "retry_and_cache",
        "target": "process_and_cache",
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
    },
    {
        "name": "ratio_of_two_extracted_fields",
        "target": "f",
        "source": '''
import requests

def f(url):
    raw = requests.get(url).json()
    a1 = raw["x"]
    a2 = a1
    a3 = a2
    b1 = raw["y"]
    b2 = b1
    b3 = b2
    return a3 / b3
''',
    },
]

GENUINE_EXAMPLES.append({
    "name": "ml_train_and_predict",
    "target": "train_and_predict",
    "source": '''
import requests
import numpy as np
import sklearn.linear_model

def train_and_predict(dataset_url, features):
    response = requests.get(dataset_url)
    raw = response.json()
    X_train = np.array(raw["X"])
    y_train = np.array(raw["y"])
    model = sklearn.linear_model.LinearRegression()
    model.fit(X_train, y_train)
    return model.predict(features)
''',
})

GENUINE_EXAMPLES.append({
    "name": "branch_ambiguous_real_computation_in_if",
    "target": "get_profile",
    "source": '''
import requests

def get_profile(user_id):
    response = requests.get(f"/users/{user_id}").json()
    if response.get("verified"):
        output = {"name": response["name"], "trust": response["score"] * 1.5}
    else:
        output = {"name": "unknown"}
    return output
''',
})

GENUINE_EXAMPLES.append({
    "name": "branch_merged_finds_real_computation_in_if",
    "target": "get_profile",
    "source": '''
import requests

def get_profile(user_id):
    response = requests.get(f"/users/{user_id}").json()
    if response.get("verified"):
        output = {"name": response["name"], "trust": response["score"] * 1.5}
    else:
        output = {"name": "unknown"}
    return output
''',
})

GENUINE_EXAMPLES.append({
    "name": "dict_reflects_best_inner_field_not_flat_cap",
    "target": "score_and_tag",
    "source": '''
import requests

def score_and_tag(url):
    data = requests.get(url).json()
    return {"tag": data["tag"], "weighted_score": data["raw_score"] * 2.5}
''',
})