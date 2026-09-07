from utils.helpers import validate_order, apply_business_rules
from services.pricing_engine import convert_and_price_order


def process_order(order_data):
    """Excluded from candidacy: every direct call here is to a locally-defined
    function -- including convert_and_price_order, which is one hop away from
    the real network call. Call-graph depth isn't modeled (stated limitation),
    so this orchestrator is invisible to the scan even though it transitively
    triggers an HTTP request."""
    validated = validate_order(order_data)
    checked = apply_business_rules(validated)
    priced = convert_and_price_order(
        checked["total"], checked["currency"], "USD", checked["is_bulk"]
    )
    return priced
