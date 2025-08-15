from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from functools import lru_cache
from ..utils.cache import get_or_set
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias, ALIAS_MAP
from ..models import db
from ..models import KeyValue
from ..schemas import OzonStockResponseItem, OzonPostingResponse, OzonPosting, OzonReturnResponse, OzonCashboxResponse
from pydantic import ValidationError, parse_obj_as


OZON_BASE = "https://api-seller.ozon.ru"


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def fetch_stocks(accounts: list[dict], ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Возвращает сумму остатков и детализацию по складам Ozon (FBO) для нескольких аккаунтов."""
    
    def _produce() -> dict:
        # Итоговые агрегированные данные
        final_total = 0
        final_total_in_transit = 0
        final_total_in_transit_from = 0
        final_by_warehouse: dict[str, int] = defaultdict(int)
        final_by_sku: dict[str, int] = defaultdict(int)
        final_by_sku_warehouses: dict[str, dict[str, int]] = {}
        final_sku_analytics: dict[str, dict] = {}

        try:
            # Сначала получим все товары в пути К клиенту
            delivering_postings = []
            for account in accounts:
                client_id = account["client_id"]
                api_key = account["api_key"]
                start_of_time = datetime(2020, 1, 1).isoformat() + "Z"
                delivering_postings.extend(_fetch_postings(client_id, api_key, start_of_time, status="delivering"))

            for p in delivering_postings:
                for prod in p.products:
                    sku_name = alias_sku(str(prod.offer_id))
                    final_sku_analytics.setdefault(sku_name, {"ads": 0, "idc": 0, "in_transit": 0, "in_transit_from": 0})
                    final_sku_analytics[sku_name]["in_transit"] += prod.quantity
                    final_total_in_transit += prod.quantity

            # Теперь получим все товары в пути ОТ клиента (возвраты)
            returning_postings = []
            for account in accounts:
                client_id = account["client_id"]
                api_key = account["api_key"]
                returning_postings.extend(_fetch_returns(client_id, api_key, status="returning"))

            for p in returning_postings:
                for prod in p.products:
                    sku_name = alias_sku(str(prod.offer_id))
                    final_sku_analytics.setdefault(sku_name, {"ads": 0, "idc": 0, "in_transit": 0, "in_transit_from": 0})
                    final_sku_analytics[sku_name]["in_transit_from"] += prod.quantity
                    final_total_in_transit_from += prod.quantity

            for account in accounts:
                client_id = account["client_id"]
                api_key = account["api_key"]
                ozon_skus = account["skus"]

                if not ozon_skus:
                    logging.warning("ozon_skus not provided for account %s, skipping.", client_id)
                    continue

                try:
                    sku_ids = [int(s) for s in ozon_skus]
                except (ValueError, TypeError):
                    logging.error("Invalid OZON_SKUS format for account %s.", client_id, exc_info=True)
                    continue

                for i in range(0, len(sku_ids), 100):
                    chunk = sku_ids[i : i + 100]
                    a_resp = requests.post(
                        f"{OZON_BASE}/v1/analytics/stocks",
                        headers=_headers(client_id, api_key),
                        json={"skus": chunk},
                        timeout=30,
                    )
                    if not a_resp.ok:
                        logging.error("Ozon analytics/stocks failed for account %s: %s %s", client_id, a_resp.status_code, a_resp.text[:300])
                        continue

                    try:
                        validated_response = parse_obj_as(OzonStockResponseItem, a_resp.json())
                        rows = validated_response.items
                    except ValidationError as e:
                        logging.error("Ozon stocks validation error for account %s: %s", client_id, e)
                        continue
                    
                    for r in rows:
                        qty = r.available_stock_count
                        transit_qty = r.transit_stock_count
                        wh_name = r.warehouse_name or "Неизвестный кластер"
                        sku_name = alias_sku(str(r.offer_id))

                        final_by_warehouse[wh_name] += qty
                        final_total += qty
                        final_by_sku[sku_name] += qty
                        
                        sku_wh = final_by_sku_warehouses.setdefault(sku_name, defaultdict(int))
                        sku_wh[wh_name] += qty
                        
                        final_sku_analytics.setdefault(sku_name, {"ads": 0, "idc": 0, "in_transit": 0, "in_transit_from": 0})
                        final_sku_analytics[sku_name]["ads"] = r.ads
                        final_sku_analytics[sku_name]["idc"] = r.idc
                        # Убираем старую логику, так как транзиты уже посчитаны
                        # final_sku_analytics[sku_name]["in_transit"] += transit_qty

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
                "total_in_transit": final_total_in_transit,
                "total_in_transit_from": final_total_in_transit_from,
                "sku_analytics": final_sku_analytics
            }
        except Exception as exc:
            logging.exception("Ozon fetch_stocks failed: %s", exc)
            raise

    cache_key = f"ozon_stocks_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


def _fetch_postings(client_id: str, api_key: str, start_time_iso: str, status: str = "") -> list:
    """Внутренняя функция для получения постингов с Ozon API."""
    
    # Для статуса 'delivering' нам нужен широкий диапазон дат
    if status == "delivering":
        since = datetime(datetime.now().year - 1, 1, 1).isoformat() + "Z"
        to = datetime.now().isoformat() + "Z"
    else:
        since = start_time_iso
        to = datetime.now().isoformat() + "Z"

    payload = {
        "dir": "asc",
        "filter": {
            "since": since,
            "to": to,
        },
        "limit": 1000,
        "offset": 0,
    }
    if status:
        payload["filter"]["status"] = status

    # Пробуем v3, если 404 - фоллбэк на v2
    try:
        resp = requests.post(f"{OZON_BASE}/v3/posting/fbo/list", headers=_headers(client_id, api_key), json=payload, timeout=30)
        if resp.status_code == 404:
            resp = requests.post(f"{OZON_BASE}/v2/posting/fbo/list", headers=_headers(client_id, api_key), json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error("Ozon API request for postings failed: %s", e)
        raise

    rj = resp.json()
    if isinstance(rj, list):
        return rj
    
    res = rj.get("result", rj)
    if isinstance(res, list):
        try:
            return parse_obj_as(list[OzonPosting], res)
        except ValidationError:
            return [] # or handle error
    
    try:
        validated_response = parse_obj_as(OzonPostingResponse, res)
        return validated_response.result
    except ValidationError:
        return [] # or handle error


def _fetch_returns(client_id: str, api_key: str, status: str = "") -> list:
    """Внутренняя функция для получения возвратов (FBO) с Ozon API."""
    payload = {
        "dir": "asc",
        "filter": {},
        "limit": 1000,
        "offset": 0,
    }
    if status:
        payload["filter"]["status"] = status
    
    try:
        resp = requests.post(
            f"{OZON_BASE}/v2/returns/fbo/list",
            headers=_headers(client_id, api_key),
            json=payload,
            timeout=30,
        )
        if resp.status_code == 404:
            # На части аккаунтов/регионов эндпоинт может отсутствовать или быть отключён.
            # В этом случае считаем, что возвратов нет, и продолжаем без ошибки.
            logging.warning("Ozon returns endpoint 404 for client %s — treating as empty.", client_id)
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error("Ozon API request for returns failed: %s", e)
        raise

    rj = resp.json()
    try:
        validated_response = parse_obj_as(OzonReturnResponse, rj)
        return validated_response.result
    except ValidationError as e:
        logging.error("Ozon returns validation error: %s", e)
        return []


def fetch_today_metrics(accounts: list[dict], tz: ZoneInfo, ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Возвращает количество заказов и выкупов за сегодня по Ozon (FBO) для нескольких аккаунтов."""
    def _produce() -> dict:
        final_ordered_count = 0
        final_purchased_count = 0
        final_ordered_sku_counts: dict[str, int] = defaultdict(int)
        final_purchased_sku_counts: dict[str, int] = defaultdict(int)

        try:
            start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

            for account in accounts:
                client_id = account["client_id"]
                api_key = account["api_key"]

                postings = _fetch_postings(client_id, api_key, start)
                for p in postings:
                    for prod in p.products:
                        qty_i = prod.quantity
                        sku_name = alias_sku(str(prod.offer_id))
                        final_ordered_sku_counts[sku_name] += qty_i
                        final_ordered_count += qty_i

                postings_delivered = _fetch_postings(client_id, api_key, start, status="delivered")
                for p in postings_delivered:
                    for prod in p.products:
                        qty_i = prod.quantity
                        sku_name = alias_sku(str(prod.offer_id))
                        final_purchased_sku_counts[sku_name] += qty_i
                        final_purchased_count += qty_i

            ordered_skus = sort_pairs_by_alias(list(final_ordered_sku_counts.items()))
            purchased_skus = sort_pairs_by_alias(list(final_purchased_sku_counts.items()))

            return {
                "ordered": final_ordered_count,
                "purchased": final_purchased_count,
                "ordered_skus": ordered_skus,
                "purchased_skus": purchased_skus,
            }
        except Exception as exc:
            logging.exception("Ozon fetch_today_metrics failed: %s", exc)
            raise

    cache_key = f"ozon_today_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


def fetch_balance(accounts: list[dict], ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Возвращает текущий баланс на счетах Ozon."""

    def _produce() -> dict:
        total_balance = 0.0
        
        for account in accounts:
            client_id = account["client_id"]
            api_key = account["api_key"]
            try:
                resp = requests.post(
                    f"{OZON_BASE}/v1/finance/cashbox/list",
                    headers=_headers(client_id, api_key),
                    json={},
                    timeout=30,
                )
                if resp.status_code == 404:
                    logging.warning(
                        "Ozon cashbox endpoint 404 for client %s — treating balance as 0.", client_id
                    )
                    continue
                resp.raise_for_status()
                rj = resp.json()
                try:
                    validated_response = parse_obj_as(OzonCashboxResponse, rj)
                except ValidationError as e:
                    logging.error("Ozon balance validation error for client %s: %s", client_id, e)
                    continue
                for cashbox in validated_response.result:
                    if cashbox.currency_code == "RUB":
                        total_balance += cashbox.balance
            except requests.RequestException as e:
                logging.error("Ozon API request for balance failed for client %s: %s", client_id, e)
                continue
            except Exception as exc:
                logging.exception("Ozon fetch_balance failed for client %s: %s", client_id, exc)
                continue
            
        return {"balance": total_balance}

    cache_key = "ozon_balance_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


