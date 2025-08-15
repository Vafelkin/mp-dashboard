from zoneinfo import ZoneInfo
import os
import sys

# Ensure project root is on sys.path when running via systemd
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from app.services.wb_api import fetch_stocks as wb_stocks, fetch_today_metrics as wb_today
from app.services.ozon_api import fetch_stocks as oz_stocks, fetch_today_metrics as oz_today
from app.models import db, StockSnapshot, DailyMetric


def main() -> None:
    app = create_app()
    with app.app_context():
        from flask import current_app
        from datetime import datetime

        tz = ZoneInfo(current_app.config.get("TIMEZONE", "Europe/Moscow"))
        ttl_short = int(current_app.config.get("CACHE_TTL_SECONDS", 120))

        wb_token = current_app.config.get("WB_API_TOKEN", "")
        ozon_client_id = current_app.config.get("OZON_CLIENT_ID", "")
        ozon_api_key = current_app.config.get("OZON_API_KEY", "")
        ozon_skus = current_app.config.get("OZON_SKUS", [])

        # Force refresh bypassing cache
        wb_st = wb_stocks(wb_token, ttl_seconds=ttl_short * 2, force=True)
        wb_td = wb_today(wb_token, tz, ttl_seconds=ttl_short, force=True)
        oz_st = oz_stocks(ozon_client_id, ozon_api_key, ozon_skus, ttl_seconds=ttl_short * 2, force=True)
        oz_td = oz_today(ozon_client_id, ozon_api_key, tz, ttl_seconds=ttl_short, force=True)

        # Persist snapshots
        try:
            # WB stocks per SKU
            for sku, qty in (wb_st.get("skus") or []):
                db.session.add(StockSnapshot(marketplace="wb", warehouse_name="TOTAL", sku=sku, quantity=int(qty)))
            # OZON stocks per SKU
            for sku, qty in (oz_st.get("skus") or []):
                db.session.add(StockSnapshot(marketplace="ozon", warehouse_name="TOTAL", sku=sku, quantity=int(qty)))

            # Update daily metrics
            def upsert_daily(mp: str, ordered: int, purchased: int) -> None:
                today_local = datetime.now(tz).date()
                row = DailyMetric.query.filter_by(marketplace=mp, date=today_local).first()
                if not row:
                    row = DailyMetric(marketplace=mp, date=today_local, ordered_count=0, purchased_count=0)
                row.ordered_count = int(ordered or 0)
                row.purchased_count = int(purchased or 0)
                db.session.add(row)

            upsert_daily("wb", wb_td.get("ordered", 0), wb_td.get("purchased", 0))
            upsert_daily("ozon", oz_td.get("ordered", 0), oz_td.get("purchased", 0))

            db.session.commit()
        except Exception:
            db.session.rollback()


if __name__ == "__main__":
    main()


