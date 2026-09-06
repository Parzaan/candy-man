import requests

FX_API_BASE = "https://api.example-fx.com/v1"


def convert_and_price_order(order_total, currency_from, currency_to, is_bulk_order):
    """Genuine logic: real branching + real computation, one external call."""
    response = requests.get(f"{FX_API_BASE}/rate/{currency_from}/{currency_to}")
    rate = response.json()["rate"]

    converted = order_total * rate

    if is_bulk_order:
        if converted > 10000:
            discount = 0.15
        elif converted > 5000:
            discount = 0.10
        else:
            discount = 0.05
        converted = converted * (1 - discount)
    else:
        converted = converted * 1.02  # small-order processing surcharge

    tax = converted * 0.0825
    return {"total": round(converted + tax, 2), "currency": currency_to}


def estimate_delivery_window(distance_km, carrier_speed_factor):
    """Pure straight-line computation, zero external calls -- not a candidate at all."""
    base_days = distance_km / (500 * carrier_speed_factor)
    buffer_days = 1 if distance_km > 2000 else 0
    return round(base_days + buffer_days, 1)
