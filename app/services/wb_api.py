from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests

from ..utils.cache import get_or_set, get_cached
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias


WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _headers(token: str) -> dict:
    return {"Authorization": token}


def fetch_stocks(token: str, ttl_seconds: int | None = None, force: bool = False) -> dict:
    cache_key = "wb_stocks"

    def _produce() -> dict:
        try:
            date_from = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
            url = f"{WB_STATS_BASE}/api/v1/supplier/stocks"
            resp = requests.get(url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            items_raw = data if isinstance(data, list) else data.get("stocks", [])
            by_warehouse: dict[str, int] = defaultdict(int)
            by_sku: dict[str, int] = defaultdict(int)
            by_sku_in_way_to: dict[str, int] = defaultdict(int)
            by_sku_in_way_from: dict[str, int] = defaultdict(int)
            by_sku_warehouses: dict[str, dict[str, int]] = {}
            total = 0
            total_in_transit = 0
            for it in items_raw:
                qty = int(it.get("quantity", 0) or 0)
                in_way_to = int(it.get("inWayToClient", 0) or 0)
                in_way_from = int(it.get("inWayFromClient", 0) or 0)
                wh_name = it.get("warehouseName") or "Неизвестно"
                by_warehouse[wh_name] += qty
                total += qty
                total_in_transit += in_way_to
                sku_key = alias_sku(str(it.get("supplierArticle")))
                by_sku[sku_key] += qty
                by_sku_in_way_to[sku_key] += in_way_to
                by_sku_in_way_from[sku_key] += in_way_from
                sku_wh = by_sku_warehouses.setdefault(sku_key, defaultdict(int))
                sku_wh[wh_name] += qty

            warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
            skus = sort_pairs_by_alias(list(by_sku.items()))
            sku_details: dict[str, list[tuple[str, int]]] = {}
            for sku_name, wh_map in by_sku_warehouses.items():
                pairs = [(w, q) for w, q in wh_map.items() if q > 0]
                pairs.sort(key=lambda x: (-x[1], x[0]))
                sku_details[sku_name] = pairs
            return {
                "total": total,
                "warehouses": warehouses,
                "skus": skus,
                "sku_details": sku_details,
                "total_in_transit": total_in_transit,
                "sku_in_way": {
                    "to_client": dict(by_sku_in_way_to),
                    "from_client": dict(by_sku_in_way_from),
                },
            }
        except Exception as exc:
            logging.exception("WB fetch_stocks failed: %s", exc)
            raise

    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


def fetch_today_metrics(token: str, tz: ZoneInfo, ttl_seconds: int | None = None, force: bool = False) -> dict:
    cache_key = "wb_today"

    def _produce() -> dict:
        try:
            start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = start.strftime("%Y-%m-%d")

            orders_url = f"{WB_STATS_BASE}/api/v1/supplier/orders"
            r_orders = requests.get(orders_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            r_orders.raise_for_status()
            orders_data = r_orders.json()
            orders_items_raw = orders_data if isinstance(orders_data, list) else orders_data.get("orders", [])

            seen_order_ids: set[str] = set()
            dedup_orders: list[dict] = []
            for it in orders_items_raw:
                if it.get("isCancel"):
                    continue
                key = str(it.get("srid"))
                if key not in seen_order_ids:
                    seen_order_ids.add(key)
                    dedup_orders.append(it)
            ordered_count = len(dedup_orders)

            sku_counts: dict[str, int] = defaultdict(int)
            for it in dedup_orders:
                sku_key = alias_sku(str(it.get("supplierArticle")))
                sku_counts[sku_key] += 1
            ordered_skus = sort_pairs_by_alias(list(sku_counts.items()))

            # Sales
            sales_url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
            r_sales = requests.get(sales_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            r_sales.raise_for_status()
            sales_data = r_sales.json()
            sales_items_raw = sales_data if isinstance(sales_data, list) else sales_data.get("sales", [])

            seen_sales_ids: set[str] = set()
            dedup_sales: list[dict] = []
            for it in sales_items_raw:
                if it.get("isCancel"):
                    continue
                key = str(it.get("srid"))
                if key not in seen_sales_ids:
                    seen_sales_ids.add(key)
                    dedup_sales.append(it)
            purchased_count = len(dedup_sales)

            purchased_sku_counts: dict[str, int] = defaultdict(int)
            for it in dedup_sales:
                sku_key = alias_sku(str(it.get("supplierArticle")))
                purchased_sku_counts[sku_key] += 1
            purchased_skus = sort_pairs_by_alias(list(purchased_sku_counts.items()))

            return {
                "ordered": ordered_count,
                "purchased": purchased_count,
                "ordered_skus": ordered_skus,
                "purchased_skus": purchased_skus,
            }
        except requests.HTTPError as http_err:
            if getattr(http_err, "response", None) is not None and http_err.response is not None and http_err.response.status_code == 429:
                cached = get_cached(cache_key, allow_stale=True)
                if cached is not None:
                    logging.warning("WB today metrics: 429, returning cached value")
                    return cached
                logging.warning("WB today metrics: 429, no cache, returning zeros")
                return {"ordered": 0, "purchased": 0, "ordered_skus": [], "purchased_skus": []}
            logging.exception("WB fetch_today_metrics failed: %s", http_err)
            raise
        except Exception as exc:
            logging.exception("WB fetch_today_metrics failed: %s", exc)
            raise

    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


