def validate_order(order_data):
    if not order_data.get("customer_id"):
        raise ValueError("missing customer_id")
    return order_data


def apply_business_rules(order_data):
    total = order_data.get("total", 0)
    is_bulk = total > 1000
    return {**order_data, "is_bulk": is_bulk, "total": total, "currency": order_data.get("currency", "USD")}
