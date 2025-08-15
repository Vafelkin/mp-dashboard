"""
Модуль для подготовки данных к отображению в шаблонах (Presenters).
"""
from typing import Any, Dict, List, Tuple


def format_sku_list(items: list[tuple[str, int]], limit: int = 8) -> list[str]:
    """Форматирует список SKU для вывода в карточке."""
    lines: list[str] = []
    if not items:
        return lines

    for sku, cnt in items[:limit]:
        lines.append(f"{sku}: {cnt}")

    if len(items) > limit:
        lines.append("…")

    return lines


def tooltip_text(details: list[tuple[str, int]]) -> str:
    """Создает текст для всплывающей подсказки из списка пар (имя, количество)."""
    if not details:
        return "Детализация недоступна"
    return "\n".join([f"{name}: {qty}" for name, qty in details])


def prepare_ozon_stock_lines(ozon_stocks_data: dict, limit: int = 8) -> list[str]:
    """Готовит строки с остатками SKU для Ozon, включая аналитику."""
    ozon_stock_sku_lines: list[str] = []
    oz_skus_full = ozon_stocks_data.get("skus", [])
    oz_analytics = ozon_stocks_data.get("sku_analytics", {})
    if not oz_skus_full:
        return ozon_stock_sku_lines

    for sku, qty in oz_skus_full[:limit]:
        line = f"{sku}: {qty}"
        # analytics = oz_analytics.get(sku)
        # if analytics:
        #     ads = analytics.get("ads", 0)
        #     idc = analytics.get("idc", 0)
        #     line += f" (продажи: ~{ads:.1f}/день, хватит на {int(idc)} дн.)"
        ozon_stock_sku_lines.append(line)

    if len(oz_skus_full) > limit:
        ozon_stock_sku_lines.append("…")

    return ozon_stock_sku_lines


def prepare_sku_tooltips(details_map: dict[str, list[tuple[str, int]]]) -> dict[str, str]:
    """Готовит словарь с подсказками для SKU."""
    sku_tooltips: dict[str, str] = {}
    if not details_map:
        return sku_tooltips

    for sku, pairs in details_map.items():
        if not pairs:
            continue
        sku_tooltips[sku] = tooltip_text(pairs)
    return sku_tooltips


def prepare_dashboard_context(wb_data: dict, ozon_data: dict, now: Any) -> dict:
    """Готовит полный контекст для шаблона дашборда."""
    
    # WB Data
    if wb_data.get("error"):
        stocks_wb_context = {"error": True}
        wb_today_context = {"error": True}
        wb_ordered_skus_lines = []
        wb_purchased_skus_lines = []
    else:
        wb_stocks = wb_data.get("stocks", {})
        wb_today = wb_data.get("today", {})
        
        # Формируем новую структуру для остатков WB
        wb_stock_items = []
        wb_skus_list = wb_stocks.get("skus", [])
        sku_in_way_data = wb_stocks.get("sku_in_way", {})
        in_way_to = sku_in_way_data.get("to_client", {})
        in_way_from = sku_in_way_data.get("from_client", {})

        for sku, qty in wb_skus_list:
            item = {
                "text": f"{sku}: {qty}",
                "sku": sku,
                "in_transit": None
            }
            to_count = in_way_to.get(sku, 0)
            from_count = in_way_from.get(sku, 0)
            if to_count > 0 or from_count > 0:
                item["in_transit"] = {"to": to_count, "from": from_count}
            wb_stock_items.append(item)

        stocks_wb_context = {
            "total": wb_stocks.get("total", 0),
            "total_in_transit": wb_stocks.get("total_in_transit", 0),
            "tooltip": tooltip_text(wb_stocks.get("warehouses", [])),
            "sku_items": wb_stock_items,
            "sku_tooltips": prepare_sku_tooltips(wb_stocks.get("sku_details", {})),
        }
        wb_today_context = wb_today
        wb_ordered_skus_lines = format_sku_list(wb_today.get("ordered_skus", []))
        wb_purchased_skus_lines = format_sku_list(wb_today.get("purchased_skus", []))

    # Ozon Data
    if ozon_data.get("error"):
        stocks_ozon_context = {"error": True}
        ozon_today_context = {"error": True}
        ozon_ordered_skus_lines = []
        ozon_purchased_skus_lines = []
        # При ошибке также задаём контекст баланса, чтобы избежать UnboundLocalError
        ozon_balance_context = {"balance": "—"}
    else:
        ozon_stocks = ozon_data.get("stocks", {})
        ozon_today = ozon_data.get("today", {})

        # Модифицируем prepare_ozon_stock_lines для добавления данных "в пути"
        ozon_sku_analytics = ozon_stocks.get("sku_analytics", {})
        ozon_sku_lines_with_transit = []
        for line in prepare_ozon_stock_lines(ozon_stocks):
            sku_name = line.split(':')[0]
            analytics = ozon_sku_analytics.get(sku_name, {})
            
            transit_to_count = analytics.get("in_transit", 0)
            if transit_to_count > 0:
                line += f' <span class="text-success">↑{transit_to_count}</span>'

            transit_from_count = analytics.get("in_transit_from", 0)
            if transit_from_count > 0:
                line += f' <span class="text-danger ms-1">↓{transit_from_count}</span>'

            ozon_sku_lines_with_transit.append(line)

        stocks_ozon_context = {
            "total": ozon_stocks.get("total", 0),
            "total_in_transit": ozon_stocks.get("total_in_transit", 0),
            "tooltip": tooltip_text(ozon_stocks.get("warehouses", [])),
            "sku_lines": ozon_sku_lines_with_transit,
            "sku_tooltips": prepare_sku_tooltips(ozon_stocks.get("sku_details", {})),
        }
        ozon_today_context = ozon_today
        ozon_ordered_skus_lines = format_sku_list(ozon_today.get("ordered_skus", []))
        ozon_purchased_skus_lines = format_sku_list(ozon_today.get("purchased_skus", []))

        ozon_balance_data = ozon_data.get("balance", {})
        ozon_balance_context = {
            "balance": f"{ozon_balance_data.get('balance', 0):,.0f} ₽".replace(",", " ")
        }

    context = {
        "stocks_wb": stocks_wb_context,
        "stocks_ozon": stocks_ozon_context,
        "wb_today": wb_today_context,
        "wb_ordered_skus_lines": wb_ordered_skus_lines,
        "wb_purchased_skus_lines": wb_purchased_skus_lines,
        "ozon_today": ozon_today_context,
        "ozon_ordered_skus_lines": ozon_ordered_skus_lines,
        "ozon_purchased_skus_lines": ozon_purchased_skus_lines,
        "ozon_balance": ozon_balance_context,
        "now": now,
    }

    return context
