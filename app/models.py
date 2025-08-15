from datetime import datetime, date

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class StockSnapshot(db.Model):
    __tablename__ = "stock_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    marketplace = db.Column(db.String(16), nullable=False)  # 'wb' | 'ozon'
    warehouse_name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(64))
    quantity = db.Column(db.Integer, nullable=False, default=0)
    captured_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class DailyMetric(db.Model):
    __tablename__ = "daily_metrics"

    id = db.Column(db.Integer, primary_key=True)
    marketplace = db.Column(db.String(16), nullable=False)  # 'wb' | 'ozon'
    date = db.Column(db.Date, nullable=False, default=date.today)
    ordered_count = db.Column(db.Integer, nullable=False, default=0)
    purchased_count = db.Column(db.Integer, nullable=False, default=0)


class KeyValue(db.Model):
    __tablename__ = "kv_store"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value_json = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


