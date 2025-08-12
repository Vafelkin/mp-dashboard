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

    context = {
        "stocks_wb": {
            "total": wb_stocks.get("total", 0),
            "tooltip": tooltip_text(wb_stocks.get("warehouses", [])),
        },
        "stocks_ozon": {
            "total": ozon_stocks.get("total", 0),
            "tooltip": tooltip_text(ozon_stocks.get("warehouses", [])),
        },
        "wb_today": wb_today,
        "ozon_today": ozon_today,
        "now": datetime.now(tz),
    }

    return render_template("dashboard.html", **context)


