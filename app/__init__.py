from flask import Flask

from config import Config
from .models import db


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    from .routes.dashboard import dashboard_bp

    app.register_blueprint(dashboard_bp)

    return app


