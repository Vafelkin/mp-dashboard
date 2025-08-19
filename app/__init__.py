from flask import Flask
from flask_caching import Cache

from config import Config
from .models import db

# Инициализация кэша
cache = Cache()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    # Настройка кэша
    cache.init_app(app)

    db.init_app(app)

    # with app.app_context():
    #     db.create_all()

    from .routes.dashboard import dashboard_bp

    app.register_blueprint(dashboard_bp)

    return app


