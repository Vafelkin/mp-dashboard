from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, render_template, request, jsonify
import logging

from ..services.wb_api import fetch_stocks as wb_fetch_stocks, fetch_today_metrics as wb_fetch_today
from ..services.ozon_api import fetch_stocks as ozon_fetch_stocks, fetch_today_metrics as ozon_fetch_today, fetch_balance as ozon_fetch_balance
from ..models import db, StockSnapshot, DailyMetric
from ..presenters import prepare_dashboard_context


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def dashboard_index():
    tz_name = current_app.config.get("TIMEZONE", "Europe/Moscow")
    tz = ZoneInfo(tz_name)

    wb_token = (current_app.config.get("WB_API_TOKEN", "") or "").strip()
    cache_ttl = int(current_app.config.get("CACHE_TTL_SECONDS", 600))
    force = request.args.get("force") == "1"

    # Fetch data from services
    if not wb_token:
        wb_data = {"error": True, "reason": "missing_wb_token"}
    else:
        try:
            wb_stocks = wb_fetch_stocks(wb_token, ttl_seconds=cache_ttl, force=force)
            wb_today = wb_fetch_today(wb_token, tz, ttl_seconds=cache_ttl, force=force)
            wb_data = {"stocks": wb_stocks, "today": wb_today}
        except Exception:
            wb_data = {"error": True}

    ozon_accounts = current_app.config.get("OZON_ACCOUNTS", [])
    if not ozon_accounts:
        ozon_data = {"error": True, "reason": "missing_ozon_accounts"}
    else:
        ozon_stocks = {}
        ozon_today = {}
        ozon_balance = {"balance": 0}
        try:
            ozon_stocks = ozon_fetch_stocks(ozon_accounts, ttl_seconds=cache_ttl, force=force)
        except Exception as exc:
            logging.exception("Ozon stocks failed: %s", exc)
        try:
            ozon_today = ozon_fetch_today(ozon_accounts, tz, ttl_seconds=cache_ttl, force=force)
        except Exception as exc:
            logging.exception("Ozon today failed: %s", exc)
        try:
            ozon_balance = ozon_fetch_balance(ozon_accounts, ttl_seconds=cache_ttl, force=force)
        except Exception as exc:
            logging.exception("Ozon balance failed: %s", exc)
        ozon_data = {"stocks": ozon_stocks, "today": ozon_today, "balance": ozon_balance}

    # Prepare context for template using the presenter
    context = prepare_dashboard_context(
        wb_data=wb_data,
        ozon_data=ozon_data,
        now=datetime.now(tz)
    )

    return render_template("dashboard.html", **context)


