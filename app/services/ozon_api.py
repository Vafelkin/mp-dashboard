from datetime import datetime
from zoneinfo import ZoneInfo


def fetch_stocks(client_id: str, api_key: str) -> dict:
    # TODO: заменить мок на реальные вызовы Ozon API
    return {
        "total": 0,
        "warehouses": [],  # [("Склад OZON A", 0)]
    }


def fetch_today_metrics(client_id: str, api_key: str, tz: ZoneInfo) -> dict:
    # TODO: заменить мок на реальные вызовы Ozon API
    _ = datetime.now(tz)
    return {"ordered": 0, "purchased": 0}


