import os
import sys
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app

# --- WB API ---
WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _wb_headers(token: str) -> dict:
    return {"Authorization": token}


def explore_wb_stocks(token: str):
    """Fetch WB stocks raw data"""
    # Docs recommend using a date for which to get stocks.
    date_from = "2023-01-01"  # Just a distant date
    url = f"{WB_STATS_BASE}/api/v1/supplier/stocks"
    params = {"dateFrom": date_from}
    print(f"--> GET {url} | params: {params}", file=sys.stderr)
    resp = requests.get(url, headers=_wb_headers(token), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def explore_wb_orders(token: str, tz: ZoneInfo):
    """Fetch WB orders for today"""
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    date_from = start.strftime("%Y-%m-%d")
    url = f"{WB_STATS_BASE}/api/v1/supplier/orders"
    params = {"dateFrom": date_from}
    print(f"--> GET {url} | params: {params}", file=sys.stderr)
    resp = requests.get(url, headers=_wb_headers(token), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def explore_wb_sales(token: str, tz: ZoneInfo):
    """Fetch WB sales for today"""
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    date_from = start.strftime("%Y-%m-%d")
    url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
    params = {"dateFrom": date_from}
    print(f"--> GET {url} | params: {params}", file=sys.stderr)
    resp = requests.get(url, headers=_wb_headers(token), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# --- Ozon API ---
OZON_BASE = "https://api-seller.ozon.ru"


def _ozon_headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def explore_ozon_stocks(client_id: str, api_key: str, skus: list[str] | None = None):
    """Fetch Ozon stocks using v1/analytics/stocks"""
    headers = _ozon_headers(client_id, api_key)
    sku_ids = []

    if skus:
        print(f"--> Using provided SKUs: {skus}", file=sys.stderr)
        try:
            # Ozon SKUs are integers
            sku_ids = [int(s) for s in skus]
        except (ValueError, TypeError):
            print("--> Error: SKUs must be valid integers.", file=sys.stderr)
            return {"error": "SKUs must be valid integers."}
    else:
        # 1. Get product list to find SKUs, as analytics endpoint requires them.
        # This endpoint seems to be unstable, so wrap it in try/except.
        try:
            print("--> Attempt 1: Fetching product list to get SKUs via /v2/product/list...", file=sys.stderr)
            url_list = f"{OZON_BASE}/v2/product/list"
            payload_list = {"filter": {"visibility": "ALL"}, "limit": 1000}
            resp_list = requests.post(
                url_list, headers=headers, json=payload_list, timeout=30
            )
            if resp_list.ok:
                products_data = resp_list.json()
                for item in products_data.get("result", {}).get("items", []):
                    sku = item.get("sku")
                    if sku:
                        sku_ids.append(sku)
            else:
                print(f"--> /v2/product/list failed with status: {resp_list.status_code}", file=sys.stderr)

        except Exception as e:
            print(f"--> /v2/product/list failed with exception: {e}", file=sys.stderr)

        # 2. If the first method failed, try to get SKUs from recent postings.
        if not sku_ids:
            try:
                print("--> Attempt 2: Fetching SKUs from recent postings via /v3/posting/fbo/list...", file=sys.stderr)
                from datetime import timedelta
                start_dt = datetime.now(ZoneInfo("Europe/Moscow")) - timedelta(days=30)
                start_iso = start_dt.isoformat()
                postings_url = f"{OZON_BASE}/v3/posting/fbo/list"
                postings_payload = {"dir": "asc", "filter": {"since": start_iso}, "limit": 200}
                resp_postings = requests.post(postings_url, headers=headers, json=postings_payload, timeout=30)

                if resp_postings.ok:
                    postings_data = resp_postings.json()
                    postings = postings_data.get("result", {}).get("postings", [])
                    
                    discovered_skus = set()
                    for p in postings:
                        for prod in p.get("products", []):
                            sku = prod.get("sku")
                            if sku:
                                discovered_skus.add(sku)
                    sku_ids = list(discovered_skus)
                    print(f"--> Discovered {len(sku_ids)} SKUs from postings.", file=sys.stderr)

                else:
                    print(f"--> /v3/posting/fbo/list failed with status: {resp_postings.status_code}", file=sys.stderr)

            except Exception as e:
                print(f"--> Getting SKUs from postings failed with exception: {e}", file=sys.stderr)
        
        # 3. Last resort: try getting info by known offer_ids
        if not sku_ids:
            try:
                from app.utils.sku_aliases import ALIAS_MAP
                known_offer_ids = list(ALIAS_MAP.keys())
                print(f"--> Attempt 3: Using known offer_ids: {known_offer_ids}", file=sys.stderr)
                url_info = f"{OZON_BASE}/v2/product/info/stocks"
                payload_info = {"offer_id": known_offer_ids, "limit": len(known_offer_ids)}
                resp_info = requests.post(url_info, headers=headers, json=payload_info, timeout=30)
                print(f"<-- Response Status for info/stocks: {resp_info.status_code}", file=sys.stderr)
                if resp_info.ok:
                    return {"stocks_by_offer_id": resp_info.json()}
            except Exception as e:
                print(f"--> Getting info by offer_id failed: {e}", file=sys.stderr)


    if not sku_ids:
        return {
            "error": "Could not find any SKUs for analytics after all attempts."
        }

    # 3. Call analytics stocks endpoint
    url_analytics = f"{OZON_BASE}/v1/analytics/stocks"
    # The API expects SKUs as integers. The field name is 'skus'.
    payload_analytics = {"skus": sku_ids}
    print(
        f"--> POST {url_analytics} with {len(sku_ids)} SKUs...", file=sys.stderr
    )
    resp_analytics = requests.post(
        url_analytics, headers=headers, json=payload_analytics, timeout=30
    )

    print(f"<-- Response Status: {resp_analytics.status_code}", file=sys.stderr)

    return {
        "analytics_stocks_request_body": payload_analytics,
        "analytics_stocks_response": resp_analytics.json(),
    }


def explore_ozon_postings(client_id: str, api_key: str, tz: ZoneInfo):
    """Fetch Ozon FBO postings for today (orders and sales/delivered)"""
    headers = _ozon_headers(client_id, api_key)
    start = datetime.now(tz).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    url = f"{OZON_BASE}/v3/posting/fbo/list"

    # All statuses (ordered)
    payload_orders = {"dir": "asc", "filter": {"since": start}, "limit": 1000}
    print(f"--> POST {url} | body: {payload_orders} (for orders)", file=sys.stderr)
    resp_orders = requests.post(url, headers=headers, json=payload_orders, timeout=30)
    resp_orders.raise_for_status()

    # Delivered status (sales)
    payload_sales = {
        "dir": "asc",
        "filter": {"since": start, "status": "delivered"},
        "limit": 1000,
    }
    print(f"--> POST {url} | body: {payload_sales} (for sales)", file=sys.stderr)
    resp_sales = requests.post(url, headers=headers, json=payload_sales, timeout=30)
    resp_sales.raise_for_status()

    return {
        "orders_today": resp_orders.json(),
        "sales_today": resp_sales.json(),
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/explore_api.py <wb|ozon> <stocks|orders|sales|postings> [skus...]", file=sys.stderr)
        print("Example: python3 scripts/explore_api.py wb stocks", file=sys.stderr)
        print("Example: python3 scripts/explore_api.py ozon stocks 2282004121", file=sys.stderr)
        return

    marketplace = sys.argv[1].lower()
    endpoint = sys.argv[2].lower()
    extra_args = sys.argv[3:]

    app = create_app()
    with app.app_context():
        # Load config
        wb_token = app.config.get("WB_API_TOKEN")
        ozon_client_id = app.config.get("OZON_CLIENT_ID")
        ozon_api_key = app.config.get("OZON_API_KEY")
        tz = ZoneInfo(app.config.get("TIMEZONE", "Europe/Moscow"))

        data = None
        try:
            if marketplace == "wb":
                if not wb_token:
                    raise ValueError("WB_API_TOKEN is not set")
                if endpoint == "stocks":
                    data = explore_wb_stocks(wb_token)
                elif endpoint == "orders":
                    data = explore_wb_orders(wb_token, tz)
                elif endpoint == "sales":
                    data = explore_wb_sales(wb_token, tz)
                else:
                    print(f"Unknown endpoint for WB: {endpoint}", file=sys.stderr)
            elif marketplace == "ozon":
                if not ozon_client_id or not ozon_api_key:
                    raise ValueError("Ozon credentials not set")
                if endpoint == "stocks":
                    data = explore_ozon_stocks(ozon_client_id, ozon_api_key, skus=extra_args)
                elif endpoint == "postings":  # covers orders and sales
                    data = explore_ozon_postings(ozon_client_id, ozon_api_key, tz)
                else:
                    print(
                        f"Unknown endpoint for Ozon: {endpoint}. Use 'stocks' or 'postings'.",
                        file=sys.stderr
                    )
            else:
                print(f"Unknown marketplace: {marketplace}", file=sys.stderr)

            if data:
                print(json.dumps(data, indent=2, ensure_ascii=False))

        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)
            if isinstance(e, requests.HTTPError):
                print("Response body:", e.response.text, file=sys.stderr)


if __name__ == "__main__":
    main()
