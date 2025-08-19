import os
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, current_app, render_template, request
import logging

from ..services.wb_api import fetch_stocks as wb_fetch_stocks, fetch_today_metrics as wb_fetch_today
from ..services.ozon_api import fetch_stocks as ozon_fetch_stocks, fetch_today_metrics as ozon_fetch_today, _make_hashable as ozon_make_hashable
from ..presenters import prepare_dashboard_context
from .. import cache


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def dashboard_index():
    if request.args.get("force") == "1":
        cache_dir = current_app.config.get("CACHE_DIR")
        if cache_dir and os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)

    tz_name = current_app.config.get("TIMEZONE", "Europe/Moscow")
    tz = ZoneInfo(tz_name)

    wb_token = (current_app.config.get("WB_API_TOKEN", "") or "").strip()

    # WB
    if not wb_token:
        wb_data = {"error": True, "reason": "missing_wb_token"}
    else:
        try:
            wb_stocks = wb_fetch_stocks(wb_token)
            wb_today = wb_fetch_today(wb_token, tz)
            wb_data = {"stocks": wb_stocks, "today": wb_today}
        except Exception as exc:
            logging.exception("WB failed: %s", exc)
            wb_data = {"error": True}

    # Ozon
    ozon_accounts = current_app.config.get("OZON_ACCOUNTS", [])
    if not ozon_accounts:
        ozon_data = {"error": True, "reason": "missing_ozon_accounts"}
    else:
        ozon_stocks = {}
        ozon_today = {}
        try:
            ozon_accounts_hashable = ozon_make_hashable(ozon_accounts)
            ozon_stocks = ozon_fetch_stocks(ozon_accounts_hashable)
        except Exception as exc:
            logging.exception("Ozon stocks failed: %s", exc)
        try:
            ozon_accounts_hashable = ozon_make_hashable(ozon_accounts)
            ozon_today = ozon_fetch_today(ozon_accounts_hashable, tz)
        except Exception as exc:
            logging.exception("Ozon today failed: %s", exc)
        ozon_data = {"stocks": ozon_stocks, "today": ozon_today}

    context = prepare_dashboard_context(
        wb_data=wb_data,
        ozon_data=ozon_data,
        now=datetime.now(tz)
    )

    # Get cache update time
    last_updated = None
    try:
        cache_dir = current_app.config.get("CACHE_DIR")
        if cache_dir and os.path.exists(cache_dir):
            files = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
            if files:
                latest_file = max(files, key=lambda f: os.path.getmtime(os.path.join(cache_dir, f)))
                last_updated = datetime.fromtimestamp(os.path.getmtime(os.path.join(cache_dir, latest_file)), tz=tz)
    except Exception:
        pass  # Ignore errors in getting cache time

    context["last_updated"] = last_updated
    context["cache_ttl_minutes"] = current_app.config.get("CACHE_DEFAULT_TIMEOUT", 1800) // 60

    return render_template("dashboard.html", **context)


