from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from functools import lru_cache
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias


OZON_BASE = "https://api-seller.ozon.ru"


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


@lru_cache(maxsize=8)
def fetch_stocks(client_id: str, api_key: str) -> dict:
    """Возвращает сумму остатков и детализацию по складам Ozon (FBO).

    Основной источник: Analytics API — v1/analytics/stocks.
    Фоллбэки: v3/v2 product info stocks как раньше, если analytics недоступен.
    """
    try:
        # 1) Список складов
        id_to_name: dict[int, str] = {}
        try:
            wh_resp = requests.post(
                f"{OZON_BASE}/v1/warehouse/list",
                headers=_headers(client_id, api_key),
                json={},
                timeout=30,
            )
            if wh_resp.ok:
                warehouses_data = wh_resp.json().get("result", [])
                for w in warehouses_data:
                    wid = w.get("warehouse_id") or w.get("warehouseId")
                    if wid is not None:
                        try:
                            id_to_name[int(wid)] = w.get("name") or str(wid)
                        except Exception:
                            pass
        except Exception:
            pass

        # Попытка 0: Analytics stocks (предпочтительно для FBO)
        by_warehouse: dict[str, int] = defaultdict(int)
        by_sku: dict[str, int] = defaultdict(int)
        by_sku_warehouses: dict[str, dict[str, int]] = {}
        total = 0
        try:
            offset = 0
            page_size = 1000
            used_analytics = False
            while True:
                a_resp = requests.post(
                    f"{OZON_BASE}/v1/analytics/stocks",
                    headers=_headers(client_id, api_key),
                    json={
                        "limit": page_size,
                        "offset": offset,
                        # фильтры оставляем пустыми для сводки по всем sku FBO
                    },
                    timeout=30,
                )
                if not a_resp.ok:
                    break
                used_analytics = True
                aj = a_resp.json()
                rows = (
                    aj.get("result", {}).get("items")
                    or aj.get("result", {}).get("rows")
                    or aj.get("result")
                    or aj.get("items")
                    or aj.get("rows")
                    or []
                )
                if not isinstance(rows, list):
                    break
                if not rows:
                    break
                for r in rows:
                    wh_id = r.get("warehouse_id") or r.get("warehouseId")
                    wh_name = id_to_name.get(int(wh_id)) if isinstance(wh_id, int) else None
                    if not wh_name:
                        wh_name = str(wh_id) if wh_id is not None else "Неизвестно"
                    qty = (
                        r.get("present")
                        or r.get("quantity")
                        or r.get("stock")
                        or r.get("in_stock")
                        or 0
                    )
                    try:
                        qty_int = int(qty)
                    except Exception:
                        qty_int = 0
                    if qty_int <= 0:
                        continue
                    by_warehouse[wh_name] += qty_int
                    total += qty_int
                    # sku
                    sku_name = alias_sku(
                        str(
                            r.get("offer_id")
                            or r.get("offerId")
                            or r.get("sku")
                            or r.get("product_id")
                            or "SKU"
                        )
                    )
                    by_sku[sku_name] += qty_int
                    sku_wh = by_sku_warehouses.setdefault(sku_name, defaultdict(int))
                    sku_wh[wh_name] += qty_int

                offset += page_size
                if len(rows) < page_size:
                    break

            if used_analytics:
                warehouses = sorted(by_warehouse.items(), key=lambda x: x[0])
                skus = sort_pairs_by_alias(list(by_sku.items()))
                sku_details: dict[str, list[tuple[str, int]]] = {}
                for sku_name, wh_map in by_sku_warehouses.items():
                    pairs = [(w, q) for w, q in wh_map.items() if q > 0]
                    pairs.sort(key=lambda x: (-x[1], x[0]))
                    sku_details[sku_name] = pairs
                return {"total": total, "warehouses": warehouses, "skus": skus, "sku_details": sku_details}
        except Exception:
            # пойдём по фоллбэкам ниже
            pass

        # 2) Список товаров (все видимые) — для фоллбэков
        product_ids: list[int] = []
        offer_ids: list[str] = []
        last_id = ""
        while True:
            resp = requests.post(
                f"{OZON_BASE}/v2/product/list",
                headers=_headers(client_id, api_key),
                json={"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": 1000},
                timeout=30,
            )
            if not resp.ok:
                break
            rj = resp.json().get("result", {})
            items = rj.get("items", [])
            for it in items:
                pid = it.get("product_id")
                if pid is not None:
                    try:
                        product_ids.append(int(pid))
                    except Exception:
                        pass
                off = it.get("offer_id") or it.get("offerId")
                if off:
                    try:
                        offer_ids.append(str(off))
                    except Exception:
                        pass
            last_id = rj.get("last_id") or ""
            if not last_id:
                break

        if not product_ids and not offer_ids:
            return {"total": 0, "warehouses": []}

        # 3) Остатки по товарам — агрегируем по складам
        by_warehouse = defaultdict(int)
        total = 0
        chunk_size = 100
        # приоритет: v3 по product_id
        used_any = False
        if product_ids:
            for i in range(0, len(product_ids), chunk_size):
                batch = product_ids[i : i + chunk_size]
                s_resp = requests.post(
                    f"{OZON_BASE}/v3/product/info/stocks",
                    headers=_headers(client_id, api_key),
                    json={"product_id": batch, "limit": len(batch)},
                    timeout=30,
                )
                if not s_resp.ok:
                    break
                used_any = True
                s_res = s_resp.json().get("result") or []
                for item in s_res:
                    for s in item.get("stocks") or []:
                        wh_id = s.get("warehouse_id") or s.get("warehouseId")
                        wh_name = None
                        try:
                            wh_name = id_to_name.get(int(wh_id)) if wh_id is not None else None
                        except Exception:
                            pass
                        if not wh_name:
                            wh_name = str(wh_id) if wh_id is not None else "Неизвестно"
                        qty = s.get("present") or s.get("quantity") or 0
                        try:
                            qty_int = int(qty)
                        except Exception:
                            qty_int = 0
                        by_warehouse[wh_name] += qty_int
                        total += qty_int

        # фоллбэк: v2 по offer_id
        if not used_any and offer_ids:
            for i in range(0, len(offer_ids), 100):
                batch = offer_ids[i : i + 100]
                s_resp = requests.post(
                    f"{OZON_BASE}/v2/product/info/stocks",
                    headers=_headers(client_id, api_key),
                    json={"offer_id": batch, "limit": len(batch)},
                    timeout=30,
                )
                if not s_resp.ok:
                    break
                res = s_resp.json().get("result") or {}
                items = res.get("items") or res.get("products") or []
                for item in items:
                    for s in item.get("stocks") or []:
                        wh_id = s.get("warehouse_id") or s.get("warehouseId")
                        wh_name = None
                        try:
                            wh_name = id_to_name.get(int(wh_id)) if wh_id is not None else None
                        except Exception:
                            pass
                        if not wh_name:
                            wh_name = str(wh_id) if wh_id is not None else "Неизвестно"
                        qty = s.get("present") or s.get("quantity") or 0
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


@lru_cache(maxsize=32)
def fetch_today_metrics(client_id: str, api_key: str, tz: ZoneInfo) -> dict:
    """Возвращает количество заказов и выкупов за сегодня по Ozon (FBO).

    Используем /v3/posting/fbo/list: без статуса — все с начала дня; со статусом delivered — выкуплено.
    """
    try:
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        orders_resp = requests.post(
            f"{OZON_BASE}/v3/posting/fbo/list",
            headers=_headers(client_id, api_key),
            json={
                "dir": "asc",
                "filter": {
                    "since": start,
                },
                "limit": 1000,
                "offset": 0,
            },
            timeout=30,
        )
        if orders_resp.status_code == 404:
            # Фоллбэк на v2
            orders_resp = requests.post(
                f"{OZON_BASE}/v2/posting/fbo/list",
                headers=_headers(client_id, api_key),
                json={
                    "dir": "asc",
                    "filter": {"since": start},
                    "limit": 1000,
                    "offset": 0,
                },
                timeout=30,
            )
        orders_resp.raise_for_status()
        rj = orders_resp.json()
        if isinstance(rj, list):
            orders_data = rj
        else:
            res = rj.get("result", rj)
            if isinstance(res, list):
                orders_data = res
            else:
                orders_data = res.get("postings") or res.get("items") or []
        ordered_count = len(orders_data)

        delivered_resp = requests.post(
            f"{OZON_BASE}/v3/posting/fbo/list",
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
        if delivered_resp.status_code == 404:
            delivered_resp = requests.post(
                f"{OZON_BASE}/v2/posting/fbo/list",
                headers=_headers(client_id, api_key),
                json={
                    "dir": "asc",
                    "filter": {"since": start, "status": "delivered"},
                    "limit": 1000,
                    "offset": 0,
                },
                timeout=30,
            )
        delivered_resp.raise_for_status()
        rj2 = delivered_resp.json()
        if isinstance(rj2, list):
            delivered_data = rj2
        else:
            res2 = rj2.get("result", rj2)
            if isinstance(res2, list):
                delivered_data = res2
            else:
                delivered_data = res2.get("postings") or res2.get("items") or []
        purchased_count = len(delivered_data)

        return {"ordered": ordered_count, "purchased": purchased_count}
    except Exception as exc:
        logging.exception("Ozon fetch_today_metrics failed: %s", exc)
        return {"ordered": 0, "purchased": 0}


