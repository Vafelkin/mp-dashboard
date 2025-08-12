from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from functools import lru_cache
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias


WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _headers(token: str) -> dict:
    # Для WB токен передаётся без префикса 'Bearer'
    return {"Authorization": token}


@lru_cache(maxsize=8)
def fetch_stocks(token: str) -> dict:
    """Возвращает суммарные остатки WB и детализацию по складам.

    Источник: Statistics API — stocks.
    Документация: см. общий раздел WB API [dev.wildberries.ru](https://dev.wildberries.ru/openapi/api-information)
    """
    try:
        # По спецификации WB для остатков используется дата с которой начинать отдачу.
        # Берём дату за год назад на случай требований фильтра.
        date_from = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
        url = f"{WB_STATS_BASE}/api/v1/supplier/stocks"
        resp = requests.get(url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Ответ может быть как массив объектов, так и объект с ключом "stocks" — обработаем оба варианта
        items = data if isinstance(data, list) else data.get("stocks", [])

        by_warehouse: dict[str, int] = defaultdict(int)
        by_sku: dict[str, int] = defaultdict(int)
        by_sku_warehouses: dict[str, dict[str, int]] = {}
        total = 0
        for it in items:
            # Возможные поля количества в разных ревизиях API
            qty = (
                it.get("quantity")
                or it.get("quantityFull")
                or it.get("stock")
                or it.get("qty")
                or 0
            )
            wh_name = it.get("warehouseName") or it.get("warehouse_name") or it.get("warehouse") or "Неизвестно"
            try:
                qty_int = int(qty)
            except Exception:
                qty_int = 0
            by_warehouse[wh_name] += qty_int
            total += qty_int

            # Агрегируем по SKU (supplierArticle предпочтительно)
            sku = (
                it.get("supplierArticle")
                or it.get("supplierarticle")
                or it.get("nmId")
                or it.get("barcode")
                or "SKU"
            )
            try:
                sku_key = alias_sku(str(sku))
            except Exception:
                sku_key = "SKU"
            by_sku[sku_key] += qty_int
            # детализация по складам для конкретного SKU
            sku_wh = by_sku_warehouses.setdefault(sku_key, defaultdict(int))
            sku_wh[wh_name] += qty_int

        warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
        skus = list(by_sku.items())
        skus = [(alias_sku(k), v) for k, v in skus]
        skus = sort_pairs_by_alias(skus)
        # Формируем детализацию по складам для каждого SKU (убираем нули)
        sku_details: dict[str, list[tuple[str, int]]] = {}
        for sku_name, wh_map in by_sku_warehouses.items():
            pairs = [(w, q) for w, q in wh_map.items() if q > 0]
            pairs.sort(key=lambda x: (-x[1], x[0]))
            sku_details[sku_name] = pairs

        return {"total": total, "warehouses": warehouses, "skus": skus, "sku_details": sku_details}
    except Exception as exc:
        logging.exception("WB fetch_stocks failed: %s", exc)
        return {"total": 0, "warehouses": [], "skus": [], "sku_details": {}}


@lru_cache(maxsize=32)
def fetch_today_metrics(token: str, tz: ZoneInfo) -> dict:
    """Считает "Заказано сегодня" и "Выкуплено сегодня" для WB.

    - Заказано: endpoint orders с dateFrom = начало текущего дня
    - Выкуплено: endpoint sales с dateFrom = начало текущего дня
    Документация: [dev.wildberries.ru](https://dev.wildberries.ru/openapi/api-information)
    """
    try:
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        date_from = start.strftime("%Y-%m-%d")

        # Orders
        orders_url = f"{WB_STATS_BASE}/api/v1/supplier/orders"
        r_orders = requests.get(orders_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
        r_orders.raise_for_status()
        orders_data = r_orders.json()
        orders_items = orders_data if isinstance(orders_data, list) else orders_data.get("orders", [])
        ordered_count = len(orders_items)

        # Аггрегация по SKU (артикул продавца предпочтительно)
        sku_counts: dict[str, int] = defaultdict(int)
        for it in orders_items:
            sku = (
                it.get("supplierArticle")
                or it.get("supplierarticle")
                or it.get("nmId")
                or it.get("barcode")
                or "SKU"
            )
            try:
                sku_str = alias_sku(str(sku))
            except Exception:
                sku_str = "SKU"
            sku_counts[sku_str] += 1

        ordered_skus = list(sku_counts.items())
        ordered_skus = sort_pairs_by_alias(ordered_skus)

        # Sales (выкуплено)
        sales_url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
        r_sales = requests.get(sales_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
        r_sales.raise_for_status()
        sales_data = r_sales.json()
        sales_items = sales_data if isinstance(sales_data, list) else sales_data.get("sales", [])
        purchased_count = len(sales_items)

        # Аггрегация по SKU для выкупов
        purchased_sku_counts: dict[str, int] = defaultdict(int)
        for it in sales_items:
            sku = (
                it.get("supplierArticle")
                or it.get("supplierarticle")
                or it.get("nmId")
                or it.get("barcode")
                or "SKU"
            )
            try:
                sku_str = alias_sku(str(sku))
            except Exception:
                sku_str = "SKU"
            purchased_sku_counts[sku_str] += 1

        purchased_skus = list(purchased_sku_counts.items())
        purchased_skus = sort_pairs_by_alias(purchased_skus)

        return {
            "ordered": ordered_count,
            "purchased": purchased_count,
            "ordered_skus": ordered_skus,
            "purchased_skus": purchased_skus,
        }
    except Exception as exc:
        logging.exception("WB fetch_today_metrics failed: %s", exc)
        return {"ordered": 0, "purchased": 0}


