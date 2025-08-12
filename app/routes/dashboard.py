from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, render_template

from ..services.wb_api import fetch_stocks as wb_fetch_stocks, fetch_today_metrics as wb_fetch_today
from ..services.ozon_api import fetch_stocks as ozon_fetch_stocks, fetch_today_metrics as ozon_fetch_today


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def dashboard_index():
    tz_name = current_app.config.get("TIMEZONE", "Europe/Moscow")
    tz = ZoneInfo(tz_name)

    wb_token = current_app.config.get("WB_API_TOKEN", "")
    ozon_client_id = current_app.config.get("OZON_CLIENT_ID", "")
    ozon_api_key = current_app.config.get("OZON_API_KEY", "")

    # Stocks
    wb_stocks = wb_fetch_stocks(wb_token)
    ozon_stocks = ozon_fetch_stocks(ozon_client_id, ozon_api_key)

    # Today metrics
    wb_today = wb_fetch_today(wb_token, tz)
    ozon_today = ozon_fetch_today(ozon_client_id, ozon_api_key, tz)

    def tooltip_text(details: list[tuple[str, int]]) -> str:
        if not details:
            return "Детализация недоступна"
        return "\n".join([f"{name}: {qty}" for name, qty in details])

    # Формируем список строк по SKU для WB
    wb_sku_lines: list[str] = []
    try:
        wb_skus = wb_today.get("ordered_skus", [])
        if wb_skus:
            for sku, cnt in wb_skus[:8]:
                wb_sku_lines.append(f"{sku}: {cnt}")
            if len(wb_skus) > 8:
                wb_sku_lines.append("…")
    except Exception:
        wb_sku_lines = []

    # Список строк по остаткам SKU (WB)
    wb_stock_sku_lines: list[str] = []
    try:
        wb_skus_full = wb_stocks.get("skus", [])
        if wb_skus_full:
            for sku, qty in wb_skus_full[:8]:
                wb_stock_sku_lines.append(f"{sku}: {qty}")
            if len(wb_skus_full) > 8:
                wb_stock_sku_lines.append("…")
    except Exception:
        wb_stock_sku_lines = []

    # Список строк по выкупленным SKU (WB)
    wb_purchased_lines: list[str] = []
    try:
        wb_purch = wb_today.get("purchased_skus", [])
        if wb_purch:
            for sku, cnt in wb_purch[:8]:
                wb_purchased_lines.append(f"{sku}: {cnt}")
            if len(wb_purch) > 8:
                wb_purchased_lines.append("…")
    except Exception:
        wb_purchased_lines = []

    # Подготовим карту подсказок по SKU для остатков WB
    wb_stock_sku_tooltips: dict[str, str] = {}
    try:
        details_map = wb_stocks.get("sku_details", {}) or {}
        for sku, pairs in details_map.items():
            if not pairs:
                continue
            wb_stock_sku_tooltips[sku] = tooltip_text(pairs)
    except Exception:
        wb_stock_sku_tooltips = {}

    context = {
        "stocks_wb": {
            "total": wb_stocks.get("total", 0),
            "tooltip": tooltip_text(wb_stocks.get("warehouses", [])),
            "sku_lines": wb_stock_sku_lines,
            "sku_tooltips": wb_stock_sku_tooltips,
        },
        "stocks_ozon": {
            "total": ozon_stocks.get("total", 0),
            "tooltip": tooltip_text(ozon_stocks.get("warehouses", [])),
        },
        "wb_today": wb_today,
        "wb_ordered_skus_lines": wb_sku_lines,
        "wb_purchased_skus_lines": wb_purchased_lines,
        "ozon_today": ozon_today,
        "now": datetime.now(tz),
    }

    return render_template("dashboard.html", **context)


