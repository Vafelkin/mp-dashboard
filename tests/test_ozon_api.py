import pytest
from unittest.mock import MagicMock
from flask import Flask
from app.services import ozon_api
from app import cache
from app.schemas import OzonStockResponse, OzonStockItem

@pytest.fixture
def app():
    """Создает экземпляр Flask-приложения для тестов."""
    app = Flask(__name__)
    app.config["CACHE_TYPE"] = "SimpleCache"
    cache.init_app(app)
    return app

@pytest.fixture
def mock_requests_post(monkeypatch):
    """Фикстура для мока requests.post"""
    mock_post = MagicMock()
    monkeypatch.setattr(ozon_api.requests, "post", mock_post)
    return mock_post

def test_fetch_stocks_aggregation(mock_requests_post, app):
    """
    Тестирует агрегацию данных по остаткам с нескольких аккаунтов Ozon.
    """
    accounts_tuple = (
        ("client1", "key1", ("101", "102")),
        ("client2", "key2", ("201",)),
    )

    # Ответ от первого аккаунта
    response1_items = [
        OzonStockItem(available_stock_count=10, transit_stock_count=1, warehouse_name="Склад 1", offer_id="101"),
        OzonStockItem(available_stock_count=5, transit_stock_count=0, warehouse_name="Склад 2", offer_id="102"),
    ]
    response1 = OzonStockResponse(items=response1_items)

    # Ответ от второго аккаунта
    response2_items = [
        OzonStockItem(available_stock_count=20, transit_stock_count=2, warehouse_name="Склад 1", offer_id="201"),
    ]
    response2 = OzonStockResponse(items=response2_items)

    mock_requests_post.side_effect = [
        MagicMock(ok=True, json=lambda: response1.model_dump()),
        MagicMock(ok=True, json=lambda: response2.model_dump()),
    ]

    with app.app_context():
        cache.clear()
        result = ozon_api.fetch_stocks(accounts_tuple)

    # Проверяем общие суммы
    assert result["total"] == 35  # 10 + 5 + 20

    # Проверяем агрегацию по складам
    assert dict(result["warehouses"])["Склад 1"] == 30  # 10 + 20
    assert dict(result["warehouses"])["Склад 2"] == 5

    # Проверяем агрегацию по SKU
    assert dict(result["skus"])["101"] == 10
    assert dict(result["skus"])["102"] == 5
    assert dict(result["skus"])["201"] == 20
