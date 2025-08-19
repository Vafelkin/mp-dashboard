import os
from dotenv import load_dotenv


# Переопределяем переменные окружения значениями из .env
load_dotenv(override=True)


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.join(BASE_DIR, 'mp_dashboard.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WB_API_TOKEN = os.environ.get("WB_API_TOKEN", "")

    # --- Ozon: поддержка нескольких магазинов ---
    OZON_ACCOUNTS = []
    i = 1
    while True:
        client_id = os.environ.get(f"OZON_CLIENT_ID_{i}")
        api_key = os.environ.get(f"OZON_API_KEY_{i}")
        skus_str = os.environ.get(f"OZON_SKUS_{i}", "")

        if not client_id or not api_key:
            break

        skus = [s.strip() for s in skus_str.split(",") if s.strip()]
        OZON_ACCOUNTS.append({
            "client_id": client_id,
            "api_key": api_key,
            "skus": skus,
        })
        i += 1
    # --- Конец блока Ozon ---

    TIMEZONE = os.environ.get("TIMEZONE", "Europe/Moscow")

    # Кэш для API-запросов (секунды) — 30 минут по умолчанию
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "1800"))

    # Настройки Flask-Caching
    CACHE_TYPE = "FileSystemCache"
    CACHE_DIR = os.path.join(BASE_DIR, "..", ".cache")
    CACHE_DEFAULT_TIMEOUT = CACHE_TTL_SECONDS


