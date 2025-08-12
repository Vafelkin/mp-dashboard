from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests


OZON_BASE = "https://api-seller.ozon.ru"


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def fetch_stocks(client_id: str, api_key: str) -> dict:
    """Возвращает сумму остатков и детализацию по складам Ozon.

    Документация: [docs.ozon.ru/api/seller](https://docs.ozon.ru/api/seller/)
    Используем v3/warehouse/list и v2/product/info/stocks для агрегации по складам.
    """
    try:
        # Получаем список складов
        # Документация: /v3/warehouse/list — метод устарел/может отсутствовать; используем актуальный /v1/warehouse/list
        wh_resp = requests.post(
            f"{OZON_BASE}/v1/warehouse/list",
            headers=_headers(client_id, api_key),
            json={},
            timeout=30,
        )
        wh_resp.raise_for_status()
        warehouses_data = wh_resp.json().get("result", [])
        id_to_name = {w.get("warehouse_id"): w.get("name") for w in warehouses_data}

        # Запрашиваем агрегированные остатки по всем товарам
        # Ozon требует список offer_id или product_id; для первого MVP возьмем общую сводку, если доступна
        # Если её нет, вернём 0 и пустую детализацию (позже добавим справочник SKU)
        # Для агрегированных остатков используем /v2/warehouse/stocks — если недоступен, вернём пусто
        stocks_url = f"{OZON_BASE}/v2/warehouse/stocks"
        s_resp = requests.post(
            stocks_url,
            headers=_headers(client_id, api_key),
            json={},
            timeout=30,
        )
        if s_resp.status_code in (400, 404):
            # На некоторых аккаунтах метод может быть недоступен. Падать не будем.
            return {"total": 0, "warehouses": []}
        s_resp.raise_for_status()
        s_data = s_resp.json()
        items = s_data.get("result") or s_data.get("stocks") or []

        by_warehouse: dict[str, int] = defaultdict(int)
        total = 0
        for it in items:
            wh_id = it.get("warehouse_id") or it.get("warehouseId") or it.get("warehouse")
            wh_name = id_to_name.get(wh_id, str(wh_id) if wh_id is not None else "Неизвестно")
            qty = it.get("present") or it.get("quantity") or it.get("stock") or 0
            try:
                qty_int = int(qty)
            except Exception:
                qty_int = 0
            by_warehouse[wh_name] += qty_int
            total += qty_int

        warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
        return {"total": total, "warehouses": warehouses}
    except Exception as exc:
        logging.exception("Ozon fetch_stocks failed: %s", exc)
        return {"total": 0, "warehouses": []}


def fetch_today_metrics(client_id: str, api_key: str, tz: ZoneInfo) -> dict:
    """Возвращает количество заказов и выкупов за сегодня по Ozon.

    Документация: [docs.ozon.ru/api/seller](https://docs.ozon.ru/api/seller/)
    Для MVP используем список orders (все статусы) и постфильтруем на сегодня; для выкупов
    используем shipments/awaiting_deliver или аналитику по delivered.
    """
    try:
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        # Orders list — считаем созданные сегодня
        # Для заказов используем postings list (FBO/FBS) — некоторые магазины работают только в одной схеме
        orders_resp = requests.post(
            f"{OZON_BASE}/v3/posting/fbs/list",
            headers=_headers(client_id, api_key),
            json={
                "dir": "asc",
                "filter": {
                    "since": start,
                    "status": "",  # все статусы
                },
                "limit": 1000,
                "offset": 0,
            },
            timeout=30,
        )
        orders_resp.raise_for_status()
        orders_data = orders_resp.json().get("result", {}).get("postings", [])
        ordered_count = len(orders_data)

        # Выкуплено: postings со статусом delivered за сегодня
        delivered_resp = requests.post(
            f"{OZON_BASE}/v3/posting/fbs/list",
            headers=_headers(client_id, api_key),
            json={
                "dir": "asc",
                "filter": {
                    "since": start,
                    "status": "delivered",
                },
                "limit": 1000,
                "offset": 0,
            },
            timeout=30,
        )
        delivered_resp.raise_for_status()
        delivered_data = delivered_resp.json().get("result", {}).get("postings", [])
        purchased_count = len(delivered_data)

        return {"ordered": ordered_count, "purchased": purchased_count}
    except Exception as exc:
        logging.exception("Ozon fetch_today_metrics failed: %s", exc)
        return {"ordered": 0, "purchased": 0}


