from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
from typing import List

from ..utils.cache import get_or_set
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias


OZON_BASE = "https://api-seller.ozon.ru"


def _headers(client_id: str, api_key: str) -> dict:
    return {
        "Client-Id": str(client_id),
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def fetch_stocks(accounts: list[dict], ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Агрегирует остатки по нескольким аккаунтам (FBO Analytics Stocks)."""

    def _produce() -> dict:
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

    cache_key = "ozon_stocks_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


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


def fetch_today_metrics(accounts: list[dict], tz: ZoneInfo, ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Подсчитывает за сегодня: заказано и выкуплено (по FBO postings)."""

    def _produce() -> dict:
        ordered_total = 0
        purchased_total = 0
        ordered_by_sku: dict[str, int] = defaultdict(int)
        purchased_by_sku: dict[str, int] = defaultdict(int)
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
                # Выкуплено: постинги delivered
                for p in _fetch_postings(client_id, api_key, start, status="delivered"):
                    for pr in p.get("products", []):
                        qty = int(pr.get("quantity", 0) or 0)
                        sku_name = alias_sku(str(pr.get("offer_id")))
                        purchased_by_sku[sku_name] += qty
                        purchased_total += qty

            return {
                "ordered": ordered_total,
                "purchased": purchased_total,
                "ordered_skus": sort_pairs_by_alias(list(ordered_by_sku.items())),
                "purchased_skus": sort_pairs_by_alias(list(purchased_by_sku.items())),
            }
        except Exception as exc:
            logging.exception("Ozon fetch_today_metrics failed: %s", exc)
            raise

    cache_key = "ozon_today_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


def fetch_balance(accounts: list[dict], ttl_seconds: int | None = None, force: bool = False) -> dict:
    """Возвращает агрегированный баланс по аккаунтам через finance transaction totals.

    По документации баланс в ЛК соответствует финансовому отчёту/сводам. Здесь берём
    totals за последние 30 дней как приблизительный показатель доступного оборота.
    Если метод недоступен/403/404 — считаем баланс 0 для данного аккаунта.
    """

    def _produce() -> dict:
        total_balance = 0.0
        try:
            date_to = datetime.utcnow().date()
            date_from = date_to.replace(day=1)
            for account in accounts:
                client_id = account["client_id"]
                api_key = account["api_key"]
                try:
                    resp = requests.post(
                        f"{OZON_BASE}/v3/finance/transaction/totals",
                        headers=_headers(client_id, api_key),
                        json={
                            "date": {
                                "from": date_from.isoformat(),
                                "to": date_to.isoformat(),
                            }
                        },
                        timeout=30,
                    )
                    if resp.status_code in (403, 404):
                        logging.warning("Ozon finance totals %s: %s", client_id, resp.status_code)
                        continue
                    resp.raise_for_status()
                    rj = resp.json()
                    # totals.total_sum может быть в разных валютах; здесь берём RUB суммы, если есть
                    totals = rj.get("result", {})
                    rub_total = 0.0
                    for k, v in totals.items():
                        try:
                            rub_total += float(v or 0)
                        except Exception:
                            pass
                    total_balance += rub_total
                except Exception as e:
                    logging.warning("Ozon finance totals failed for %s: %s", client_id, e)
                    continue
            return {"balance": total_balance}
        except Exception as exc:
            logging.exception("Ozon fetch_balance failed: %s", exc)
            raise

    cache_key = "ozon_balance_multi"
    return get_or_set(cache_key, ttl_seconds, _produce, force=force)


