from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import logging
import requests
import json
from pydantic import ValidationError

from .. import cache
from ..utils.sku_aliases import alias_sku, sort_pairs_by_alias
from ..utils.cache_utils import get_timeout_to_next_half_hour
from ..models import db
from ..models import KeyValue
from ..schemas import WBStockItem, WBOrderItem, WBSaleItem


WB_STATS_BASE = "https://statistics-api.wildberries.ru"


def _headers(token: str) -> dict:
    return {"Authorization": token}


@cache.memoize(timeout=get_timeout_to_next_half_hour())
def fetch_stocks(token: str) -> dict:
    """
    Загружает и агрегирует данные об остатках на складах Wildberries.

    Возвращает словарь с общей суммой остатков, детализацией по складам,
    по SKU, а также информацией о товарах в пути к/от клиента.
    В случае ошибки API пытается загрузить данные из персистентного кэша.
    """
    day_key = f"wb_stocks"
    try:
        # Запрашиваем данные за длительный период, чтобы получить все активные SKU
        date_from = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
        url = f"{WB_STATS_BASE}/api/v1/supplier/stocks"
        resp = requests.get(url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        # Валидация
        validated_items = [WBStockItem.model_validate(item) for item in data]

        by_warehouse: dict[str, int] = defaultdict(int)
        by_sku: dict[str, int] = defaultdict(int)
        by_sku_in_way_to: dict[str, int] = defaultdict(int)
        by_sku_in_way_from: dict[str, int] = defaultdict(int)
        by_sku_warehouses: dict[str, dict[str, int]] = {}
        total = 0
        total_in_transit = 0
        for it in validated_items:
            qty = it.quantity
            in_way_to = it.in_way_to_client
            in_way_from = it.in_way_from_client
            wh_name = it.warehouse_name or "Неизвестно"
            by_warehouse[wh_name] += qty
            total += qty
            total_in_transit += in_way_to
            sku_key = alias_sku(str(it.supplier_article))
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
        result = {
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
        _save_to_persistent_cache(day_key, result)
        return result
    except (ValidationError, Exception) as exc:
        logging.exception("WB fetch_stocks failed: %s", exc)
        cached = _load_from_persistent_cache(day_key)
        if cached:
            return cached
        raise


def _fetch_and_deduplicate_items(url: str, token: str, date_from: str, tz: ZoneInfo, item_key: str, date_field: str, id_field: str, pydantic_model) -> list[dict]:
    """Запрашивает данные (заказы/продажи), фильтрует по дате и убирает дубликаты."""
    resp = requests.get(url, headers=_headers(token), params={"dateFrom": date_from}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items_raw = data if isinstance(data, list) else data.get(item_key, [])
    
    # Валидация
    validated_items = [pydantic_model.model_validate(item) for item in items_raw]

    seen_ids: set[str] = set()
    dedup_items: list[dict] = []
    today_start_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    for item in validated_items:
        item_date_utc = datetime.fromisoformat(item.date)
        item_date_local = item_date_utc.astimezone(tz)

        if item_date_local < today_start_local:
            continue
        
        if item.is_cancel:
            continue
            
        key = str(getattr(item, id_field))
        if key not in seen_ids:
            seen_ids.add(key)
            dedup_items.append(item.model_dump())
            
    return dedup_items


@cache.memoize(timeout=get_timeout_to_next_half_hour())
def fetch_today_metrics(token: str, tz: ZoneInfo) -> dict:
    """
    Загружает и агрегирует данные о заказах и продажах за сегодняшний день по московскому времени.

    Возвращает словарь с количеством заказов и продаж, а также с детализацией
    по каждому SKU для отображения в интерактивных списках.
    В случае ошибки API пытается загрузить данные из персистентного кэша.
    """
    day_key = f"wb_today:{datetime.now(tz).date().isoformat()}"
    try:
        # Запрашиваем данные с начала вчерашнего дня, чтобы гарантированно
        # захватить все события, произошедшие сегодня по UTC.
        start_utc = datetime.now(ZoneInfo("UTC")).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        date_from = start_utc.strftime("%Y-%m-%d")

        # Orders
        orders_url = f"{WB_STATS_BASE}/api/v1/supplier/orders"
        dedup_orders = _fetch_and_deduplicate_items(orders_url, token, date_from, tz, "orders", "date", "srid", WBOrderItem)
        ordered_count = len(dedup_orders)

        ordered_skus_details: dict[str, list] = defaultdict(list)
        for it in dedup_orders:
            sku_key = alias_sku(str(it.get("supplier_article")))
            order_date_utc = datetime.fromisoformat(it.get("date"))
            order_date_local = order_date_utc.astimezone(tz)
            
            details = {
                "time": order_date_local.strftime('%H:%M'),
                "city": it.get("oblast_okrug_name", "Неизвестно"),
                "warehouse": it.get("warehouse_name", "Неизвестно"),
            }
            ordered_skus_details[sku_key].append(details)
        
        # Сортируем заказы внутри каждого SKU по времени
        for sku in ordered_skus_details:
            ordered_skus_details[sku].sort(key=lambda x: x['time'])

        # Sales
        sales_url = f"{WB_STATS_BASE}/api/v1/supplier/sales"
        dedup_sales = _fetch_and_deduplicate_items(sales_url, token, date_from, tz, "sales", "date", "srid", WBSaleItem)
        purchased_count = len(dedup_sales)

        purchased_skus_details: dict[str, list] = defaultdict(list)
        for it in dedup_sales:
            sku_key = alias_sku(str(it.get("supplier_article")))
            sale_date_utc = datetime.fromisoformat(it.get("date"))
            sale_date_local = sale_date_utc.astimezone(tz)
            
            details = {
                "time": sale_date_local.strftime('%H:%M'),
                "city": it.get("oblast_okrug_name", "Неизвестно"),
                "warehouse": it.get("warehouse_name", "Неизвестно"),
            }
            purchased_skus_details[sku_key].append(details)

        # Сортируем продажи внутри каждого SKU по времени
        for sku in purchased_skus_details:
            purchased_skus_details[sku].sort(key=lambda x: x['time'])

        purchased_sku_counts: dict[str, int] = defaultdict(int)
        for it in dedup_sales:
            sku_key = alias_sku(str(it.get("supplier_article")))
            purchased_sku_counts[sku_key] += 1
        purchased_skus = sort_pairs_by_alias(list(purchased_sku_counts.items()))

        result = {
            "ordered": ordered_count,
            "purchased": purchased_count,
            "ordered_skus_details": ordered_skus_details,
            "purchased_skus_details": purchased_skus_details,
            "purchased_skus": purchased_skus,
        }
        _save_to_persistent_cache(day_key, result)
        return result
    except (ValidationError, Exception) as exc:
        logging.exception("WB fetch_today_metrics failed: %s", exc)
        cached = _load_from_persistent_cache(day_key)
        if cached:
            return cached
        raise


def _save_to_persistent_cache(key: str, data: dict):
    """Сохраняет данные в резервный кэш в БД."""
    try:
        row = KeyValue.query.filter_by(key=key).first()
        if not row:
            row = KeyValue(key=key)
        row.value_json = json.dumps(data, ensure_ascii=False)
        row.updated_at = datetime.utcnow()
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logging.exception("Failed to save to persistent cache")


def _load_from_persistent_cache(key: str) -> dict | None:
    """Загружает данные из резервного кэша в БД."""
    try:
        row = KeyValue.query.filter_by(key=key).first()
        if row and row.value_json:
            logging.warning("Returning data from persistent cache for key %s", key)
            return json.loads(row.value_json)
    except Exception:
        logging.exception("Failed to load from persistent cache")
    return None


