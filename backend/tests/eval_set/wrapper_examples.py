"""
Evaluation Set: thin wrapper implementations
===============================================
Each entry is a small, self-contained source snippet plus the qualified name
of the one function inside it that should be scored. These are all thin
wrappers around a third-party call -- Candy-Man SHOULD flag every one of
them. Several are deliberately "tricky" (validation padding, logging,
class-method adapters, multiple branches) because those are exactly the
shapes wrappers use to *look* more substantial than they are.
"""

WRAPPER_EXAMPLES = [
    {
        "name": "direct_inline_return",
        "target": "get_user",
        "source": '''
import requests

def get_user(user_id):
    return requests.get(f"https://api.example.com/users/{user_id}")
''',
    },
    {
        "name": "assigned_result_passthrough",
        "target": "fetch_data",
        "source": '''
import requests

def fetch_data(url):
    result = requests.get(url)
    return result
''',
    },
    {
        "name": "method_extraction_thin",
        "target": "fetch_json",
        "source": '''
import requests

def fetch_json(url):
    response = requests.get(url)
    return response.json()
''',
    },
    {
        "name": "no_op_default_guard",
        "target": "get_config",
        "source": '''
import requests

def get_config(key):
    result = requests.get(f"/config/{key}").json()
    return result or {}
''',
    },
    {
        "name": "validation_padded_passthrough",
        "target": "validated_fetch",
        "source": '''
import requests

def validated_fetch(url):
    if not url:
        raise ValueError("url required")
    if not url.startswith("http"):
        raise ValueError("bad scheme")
    try:
        resp = requests.get(url)
    except Exception as exc:
        raise RuntimeError("fetch failed") from exc
    return resp.json()
''',
    },
    {
        "name": "class_method_adapter",
        "target": "ApiClient.get_invoice",
        "source": '''
import stripe

class ApiClient:
    def get_invoice(self, invoice_id):
        return stripe.Invoice.retrieve(invoice_id)
''',
    },
    {
        "name": "loop_forward_only",
        "target": "fetch_all_users",
        "source": '''
import requests

def fetch_all_users(user_ids):
    results = []
    for uid in user_ids:
        results.append(requests.get(f"/users/{uid}").json())
    return results
''',
    },
    {
        "name": "logging_then_forward",
        "target": "get_and_log",
        "source": '''
import requests
import logging

def get_and_log(url):
    logging.info("fetching %s", url)
    response = requests.get(url)
    return response.json()
''',
    },
    {
        "name": "multi_return_all_passthrough",
        "target": "get_by_env",
        "source": '''
import requests

def get_by_env(env, resource_id):
    if env == "prod":
        return requests.get(f"https://prod.api/{resource_id}").json()
    else:
        return requests.get(f"https://staging.api/{resource_id}").json()
''',
    },
    {
        "name": "from_import_class_method_adapter",
        "target": "charge_card",
        "source": '''
from stripe import Charge

def charge_card(amount, token):
    return Charge.create(amount=amount, currency="usd", source=token)
''',
    },
    {
        "name": "kwargs_adapter",
        "target": "create_session",
        "source": '''
import requests

def create_session(**kwargs):
    return requests.Session(**kwargs)
''',
    },
]
