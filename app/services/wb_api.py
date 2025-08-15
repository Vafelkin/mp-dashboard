from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from functools import lru_cache
from ..utils.cache import get_or_set, get_cached
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias
from ..schemas import WBStockItem, WBOrderItem, WBSaleItem
from pydantic import ValidationError, parse_obj_as


WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _headers(token: str) -> dict:
    # Для WB токен передаётся без префикса 'Bearer'
    return {"Authorization": token}


def fetch_stocks(token: str, ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Возвращает суммарные остатки WB и детализацию по складам.

    Источник: Statistics API — stocks.
    Документация: см. общий раздел WB API [dev.wildberries.ru](https://dev.wildberries.ru/openapi/api-information)
    """
    cache_key = f"wb_stocks"

    def _produce() -> dict:
        try:
            # По спецификации WB для остатков используется дата с которой начинать отдачу.
            # Берём дату за год назад на случай требований фильтра.
            date_from = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
            url = f"{WB_STATS_BASE}/api/v1/supplier/stocks"
            resp = requests.get(url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            items_raw = data if isinstance(data, list) else data.get("stocks", [])
            try:
                items = parse_obj_as(list[WBStockItem], items_raw)
            except ValidationError as e:
                logging.error("WB stocks response validation error: %s", e)
                raise

            by_warehouse: dict[str, int] = defaultdict(int)
            by_sku: dict[str, int] = defaultdict(int)
            by_sku_in_way_to: dict[str, int] = defaultdict(int)
            by_sku_in_way_from: dict[str, int] = defaultdict(int)
            by_sku_warehouses: dict[str, dict[str, int]] = {}
            total = 0
            total_in_transit = 0
            for it in items:
                qty = it.quantity
                in_way_to = it.in_way_to_client
                in_way_from = it.in_way_from_client

                wh_name = it.warehouse_name or "Неизвестно"
                by_warehouse[wh_name] += qty
                total += qty
                total_in_transit += in_way_to # Оставляем старую логику для общего числа

                sku_key = alias_sku(str(it.supplier_article))

                by_sku[sku_key] += qty
                by_sku_in_way_to[sku_key] += in_way_to
                by_sku_in_way_from[sku_key] += in_way_from
                sku_wh = by_sku_warehouses.setdefault(sku_key, defaultdict(int))
                sku_wh[wh_name] += qty

            warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
            skus = sort_pairs_by_alias(list(by_sku.items()))

            # Формируем детализацию по складам для каждого SKU (убираем нули)
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
                }
            }
        except Exception as exc:
            logging.exception("WB fetch_stocks failed: %s", exc)
            raise

    # Если не force и задан ttl, возвращаем прошлое значение из кэша; иначе считаем
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


def fetch_today_metrics(token: str, tz: ZoneInfo, ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Считает "Заказано сегодня" и "Выкуплено сегодня" для WB.

    - Заказано: endpoint orders с dateFrom = начало текущего дня
    - Выкуплено: endpoint sales с dateFrom = начало текущего дня
    Документация: [dev.wildberries.ru](https://dev.wildberries.ru/openapi/api-information)
    """

    cache_key = f"wb_today"

    def _produce() -> dict:
        try:
            start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = start.strftime("%Y-%m-%d")

            # Orders
            orders_url = f"{WB_STATS_BASE}/api/v1/supplier/orders"
            r_orders = requests.get(orders_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            r_orders.raise_for_status()
            orders_data = r_orders.json()
            orders_items_raw = orders_data if isinstance(orders_data, list) else orders_data.get("orders", [])
            try:
                orders_items = parse_obj_as(list[WBOrderItem], orders_items_raw)
            except ValidationError as e:
                logging.error("WB orders response validation error: %s", e)
                raise

            seen_order_ids: set[str] = set()
            dedup_orders: list[WBOrderItem] = []
            for it in orders_items:
                if it.is_cancel:
                    continue
                key = str(it.srid)
                if key not in seen_order_ids:
                    seen_order_ids.add(key)
                    dedup_orders.append(it)
            ordered_count = len(dedup_orders)

            sku_counts: dict[str, int] = defaultdict(int)
            for it in dedup_orders:
                sku_key = alias_sku(str(it.supplier_article))
                sku_counts[sku_key] += 1

            ordered_skus = list(sku_counts.items())
            ordered_skus = sort_pairs_by_alias(ordered_skus)

            # Sales (выкуплено)
            sales_url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
            r_sales = requests.get(sales_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
            r_sales.raise_for_status()
            sales_data = r_sales.json()
            sales_items_raw = sales_data if isinstance(sales_data, list) else sales_data.get("sales", [])
            try:
                sales_items = parse_obj_as(list[WBSaleItem], sales_items_raw)
            except ValidationError as e:
                logging.error("WB sales response validation error: %s", e)
                raise

            seen_sales_ids: set[str] = set()
            dedup_sales: list[WBSaleItem] = []
            for it in sales_items:
                if it.is_cancel:
                    continue
                key = str(it.srid)
                if key not in seen_sales_ids:
                    seen_sales_ids.add(key)
                    dedup_sales.append(it)
            purchased_count = len(dedup_sales)

            purchased_sku_counts: dict[str, int] = defaultdict(int)
            for it in dedup_sales:
                sku_key = alias_sku(str(it.supplier_article))
                purchased_sku_counts[sku_key] += 1

            purchased_skus = list(purchased_sku_counts.items())
            purchased_skus = sort_pairs_by_alias(purchased_skus)

            return {
                "ordered": ordered_count,
                "purchased": purchased_count,
                "ordered_skus": ordered_skus,
                "purchased_skus": purchased_skus,
            }
        except requests.HTTPError as http_err:
            # Мягкая деградация при rate limit 429: показываем последнее значение из кэша
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


