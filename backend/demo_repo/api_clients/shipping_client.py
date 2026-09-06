import requests

SHIPPING_API_BASE = "https://api.example-shipping.com/v1"


def get_shipping_quote(order_id, api_key):
    """Thin wrapper: fetch a shipping quote and forward two fields, renamed."""
    response = requests.get(
        f"{SHIPPING_API_BASE}/quotes/{order_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    data = response.json()
    return {
        "rate": data["rate"],
        "carrier": data["carrier_name"],
    }


def track_package(tracking_number, api_key):
    """Another thin wrapper, no branches, no computed fields."""
    response = requests.get(
        f"{SHIPPING_API_BASE}/track/{tracking_number}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return response.json()
