import requests

def fetch_legacy_report(report_id)
    # Missing colon above -- deliberate SyntaxError to test Step 0 resilience.
    response = requests.get(f"https://old-internal-api/reports/{report_id}")
    return response.json()
