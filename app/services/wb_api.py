from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests


WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _headers(token: str) -> dict:
    # Для WB токен передаётся без префикса 'Bearer'
    return {"Authorization": token}


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

        warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
        return {"total": total, "warehouses": warehouses}
    except Exception as exc:
        logging.exception("WB fetch_stocks failed: %s", exc)
        return {"total": 0, "warehouses": []}


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

        # Sales (выкуплено)
        sales_url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
        r_sales = requests.get(sales_url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
        r_sales.raise_for_status()
        sales_data = r_sales.json()
        sales_items = sales_data if isinstance(sales_data, list) else sales_data.get("sales", [])
        purchased_count = len(sales_items)

        return {"ordered": ordered_count, "purchased": purchased_count}
    except Exception as exc:
        logging.exception("WB fetch_today_metrics failed: %s", exc)
        return {"ordered": 0, "purchased": 0}


