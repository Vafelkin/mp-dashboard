import os
from dotenv import load_dotenv


load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(BASE_DIR, 'mp_dashboard.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WB_API_TOKEN = os.environ.get("WB_API_TOKEN", "")
    OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
    OZON_API_KEY = os.environ.get("OZON_API_KEY", "")

    TIMEZONE = os.environ.get("TIMEZONE", "Europe/Moscow")


