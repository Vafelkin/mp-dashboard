import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
from flask import Flask
from app.services import wb_api
from app import cache

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

@pytest.fixture
def app():
    """Создает экземпляр Flask-приложения для тестов."""
    app = Flask(__name__)
    app.config["CACHE_TYPE"] = "SimpleCache"
    cache.init_app(app)
    return app

@pytest.fixture
def mock_requests_get(monkeypatch):
    """Фикстура для мока requests.get"""
    mock_get = MagicMock()
    monkeypatch.setattr(wb_api.requests, "get", mock_get)
    return mock_get

def test_fetch_today_metrics_filtering(mock_requests_get, app):
    """
    Тестирует корректность фильтрации заказов и продаж в fetch_today_metrics.
    Проверяет, что:
    - Заказы/продажи за вчерашний день отфильтровываются.
    - Отмененные (isCancel=True) заказы/продажи игнорируются.
    - Дубликаты по 'srid' удаляются.
    """
    today_local = datetime.now(MOSCOW_TZ)
    yesterday_local = today_local - timedelta(days=1)

    mock_orders_response = {
        "orders": [
            # 1. Корректный сегодняшний заказ
            {"srid": "order1", "date": today_local.isoformat(), "isCancel": False, "supplierArticle": "art1", "oblastOkrugName": "MSK", "warehouseName": "Kole"},
            # 2. Дубликат сегодняшнего заказа
            {"srid": "order1", "date": today_local.isoformat(), "isCancel": False, "supplierArticle": "art1", "oblastOkrugName": "MSK", "warehouseName": "Kole"},
            # 3. Отмененный сегодняшний заказ
            {"srid": "order2", "date": today_local.isoformat(), "isCancel": True, "supplierArticle": "art2", "oblastOkrugName": "SPB", "warehouseName": "Utka"},
            # 4. Вчерашний заказ
            {"srid": "order3", "date": yesterday_local.isoformat(), "isCancel": False, "supplierArticle": "art3", "oblastOkrugName": "EKB", "warehouseName": "Elek"},
            # 5. Еще один корректный сегодняшний заказ
            {"srid": "order4", "date": today_local.isoformat(), "isCancel": False, "supplierArticle": "art1", "oblastOkrugName": "MSK", "warehouseName": "Kole"},
        ]
    }
    
    # Для продаж используем аналогичную логику, но с одним валидным случаем
    mock_sales_response = {
        "sales": [
            {"srid": "sale1", "date": today_local.isoformat(), "isCancel": False, "supplierArticle": "art1", "oblastOkrugName": "MSK", "warehouseName": "Kole"},
            {"srid": "sale2", "date": yesterday_local.isoformat(), "isCancel": False, "supplierArticle": "art2", "oblastOkrugName": "SPB", "warehouseName": "Utka"},
        ]
    }

    mock_requests_get.side_effect = [
        MagicMock(ok=True, json=lambda: mock_orders_response),
        MagicMock(ok=True, json=lambda: mock_sales_response),
    ]

    with app.app_context():
        # Мокаем кэш, чтобы он не мешал
        wb_api.cache.clear()

        # Вызываем тестируемую функцию
        metrics = wb_api.fetch_today_metrics("fake_token", MOSCOW_TZ)

    # Проверяем, что заказов 2 (order1 и order4), а не 5
    assert metrics["ordered"] == 2
    # Проверяем, что продажа 1 (sale1), а не 2
    assert metrics["purchased"] == 1
    
    # Проверяем детализацию
    assert len(metrics["ordered_skus_details"]["art1"]) == 2
    assert "art2" not in metrics["ordered_skus_details"]
    assert "art3" not in metrics["ordered_skus_details"]
    
    assert len(metrics["purchased_skus_details"]["art1"]) == 1
    assert "art2" not in metrics["purchased_skus_details"]
