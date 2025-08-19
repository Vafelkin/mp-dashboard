from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from typing import List, Tuple

from .. import cache
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias
from ..utils.cache_utils import get_timeout_to_next_half_hour


OZON_BASE = "https://api-seller.ozon.ru"


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def _make_hashable(accounts: list[dict]) -> Tuple[Tuple[str, str, Tuple[str, ...]], ...]:
    return tuple(
        (acc['client_id'], acc['api_key'], tuple(sorted(acc.get('skus', []))))
        for acc in sorted(accounts, key=lambda x: x['client_id'])
    )

@cache.memoize(timeout=get_timeout_to_next_half_hour)
def fetch_stocks(accounts_tuple: Tuple[Tuple[str, str, Tuple[str, ...]], ...]) -> dict:
    """Агрегирует остатки по нескольким аккаунтам (FBO Analytics Stocks)."""
    accounts = [
        {'client_id': acc[0], 'api_key': acc[1], 'skus': list(acc[2])}
        for acc in accounts_tuple
    ]

    final_total = 0
    final_by_warehouse: dict[str, int] = defaultdict(int)
    final_by_sku: dict[str, int] = defaultdict(int)
    final_by_sku_warehouses: dict[str, dict[str, int]] = {}

    try:
        for account in accounts:
            client_id = account["client_id"]
            api_key = account["api_key"]
            ozon_skus = account.get("skus", [])
            if not ozon_skus:
                continue
            # analytics/stocks поддерживает до 100 SKU за раз
            sku_ids: List[int] = []
            for s in ozon_skus:
                try:
                    sku_ids.append(int(s))
                except Exception:
                    pass
            for i in range(0, len(sku_ids), 100):
                chunk = sku_ids[i : i + 100]
                resp = requests.post(
                    f"{OZON_BASE}/v1/analytics/stocks",
                    headers=_headers(client_id, api_key),
                    json={"skus": chunk},
                    timeout=30,
                )
                if not resp.ok:
                    logging.warning("Ozon analytics/stocks failed %s: %s", client_id, resp.status_code)
                    continue
                rj = resp.json()
                for row in rj.get("items", []):
                    qty = int(row.get("available_stock_count", 0) or 0)
                    wh_name = row.get("warehouse_name") or "Неизвестный кластер"
                    sku_name = alias_sku(str(row.get("offer_id")))
                    final_total += qty
                    final_by_warehouse[wh_name] += qty
                    final_by_sku[sku_name] += qty
                    sku_wh = final_by_sku_warehouses.setdefault(sku_name, defaultdict(int))
                    sku_wh[wh_name] += qty

        warehouses = sorted(final_by_warehouse.items(), key=lambda x: x[0])
        skus = sort_pairs_by_alias(list(final_by_sku.items()))
        sku_details: dict[str, list[tuple[str, int]]] = {}
        for sku_name, wh_map in final_by_sku_warehouses.items():
            pairs = [(w, q) for w, q in wh_map.items() if q > 0]
            pairs.sort(key=lambda x: (-x[1], x[0]))
            sku_details[sku_name] = pairs

        return {
            "total": final_total,
            "warehouses": warehouses,
            "skus": skus,
            "sku_details": sku_details,
        }
    except Exception as exc:
        logging.exception("Ozon fetch_stocks failed: %s", exc)
        raise


def _fetch_postings(client_id: str, api_key: str, start_iso: str, status: str | None = None) -> list:
    payload = {
        "dir": "asc",
        "filter": {"since": start_iso, "to": datetime.now().isoformat() + "Z"},
        "limit": 1000,
        "offset": 0,
    }
    if status:
        payload["filter"]["status"] = status
    # Официально актуальны v2 для FBO
    resp = requests.post(f"{OZON_BASE}/v2/posting/fbo/list", headers=_headers(client_id, api_key), json=payload, timeout=30)
    resp.raise_for_status()
    rj = resp.json()
    result = rj.get("result", rj)
    return result if isinstance(result, list) else []


@cache.memoize(timeout=get_timeout_to_next_half_hour)
def fetch_today_metrics(accounts_tuple: Tuple[Tuple[str, str, Tuple[str, ...]], ...], tz: ZoneInfo) -> dict:
    """Подсчитывает за сегодня: заказано (по FBO postings)."""
    accounts = [
        {'client_id': acc[0], 'api_key': acc[1], 'skus': list(acc[2])}
        for acc in accounts_tuple
    ]

    ordered_total = 0
    ordered_by_sku: dict[str, int] = defaultdict(int)
    try:
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        for account in accounts:
            client_id = account["client_id"]
            api_key = account["api_key"]
            # Заказано: все постинги с начала суток (без статуса)
            for p in _fetch_postings(client_id, api_key, start):
                for pr in p.get("products", []):
                    qty = int(pr.get("quantity", 0) or 0)
                    sku_name = alias_sku(str(pr.get("offer_id")))
                    ordered_by_sku[sku_name] += qty
                    ordered_total += qty
        
        return {
            "ordered": ordered_total,
            "purchased": 0, # Больше не запрашиваем
            "ordered_skus": sort_pairs_by_alias(list(ordered_by_sku.items())),
            "purchased_skus": [], # Больше не запрашиваем
        }
    except Exception as exc:
        logging.exception("Ozon fetch_today_metrics failed: %s", exc)
        raise


