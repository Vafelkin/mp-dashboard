from datetime import datetime
from zoneinfo import ZoneInfo


def fetch_stocks(token: str) -> dict:
    # TODO: заменить мок на реальные вызовы WB API
    return {
        "total": 0,
        "warehouses": [],  # [("Склад A", 0), ("Склад B", 0)]
    }


def fetch_today_metrics(token: str, tz: ZoneInfo) -> dict:
    # TODO: заменить мок на реальные вызовы WB API
    _ = datetime.now(tz)
    return {"ordered": 0, "purchased": 0}


