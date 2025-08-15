# MP Dashboard — Wildberries + Ozon (FBO)

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Flask 3](https://img.shields.io/badge/Flask-3.0-black?logo=flask)
![Gunicorn](https://img.shields.io/badge/Gunicorn-21-green)
![Nginx](https://img.shields.io/badge/Nginx-reverse__proxy-009639?logo=nginx&logoColor=white)
![OS Linux](https://img.shields.io/badge/OS-Linux-FCC624?logo=linux&logoColor=black)
![Status](https://img.shields.io/badge/status-prod--ready-success)
![License](https://img.shields.io/badge/license-internal-lightgrey)

Мини‑портал для мониторинга показателей по Wildberries и Ozon:
- Остатки на складах
- Заказано сегодня
- Выкуплено сегодня (WB)
- Детализация по SKU (алиасы) и по складам (тултипы у позиций)

Интерфейс: две колонки — слева Wildberries, справа Ozon.

## Стек
- Python 3.12, Flask, Gunicorn
- Bootstrap 5 (Bootswatch Cosmo)
- Nginx
- SQLite (MVP)

## Структура


## Конфигурация
 (не коммитится):

- WB docs: https://dev.wildberries.ru/openapi/api-information
- Ozon docs: https://docs.ozon.ru/api/seller/

## Запуск (dev)


## Продакшн (кратко)
- systemd: Gunicorn на 127.0.0.1:8001
- Nginx: reverse proxy :80 → 127.0.0.1:8001

## Источники данных
- WB Statistics API: stocks/orders/sales c  (начало суток)
- Ozon Seller API:
  - Остатки FBO: analytics/stocks
  - Заказано/выкуплено: posting FBO list (v2)

## Алиасы SKU
 — алиасы и порядок отображения (Кронштейны → Карточки → Пакеты 8 → Пакеты 5 → Пакеты 2).

## Roadmap

- Данные и доменная логика
  - [x] Агрегация WB/Ozon (FBO) по складам и SKU
  - [x] Алиасы SKU и пользовательский порядок
  - [ ] Фильтры: склады, SKU, период (день/неделя/месяц)
  - [ ] Графики 14/30/90 дней (заказы/выкупы/остатки)
  - [ ] Экспорт CSV/JSON

- UX/UI
  - [x] Тултипы по складам у SKU
  - [ ] Тёмная тема
  - [ ] Автообновление виджетов (websocket/long polling)
  - [ ] Страница «Справка/документация» в UI

- Производительность и устойчивость
  - [x] In‑process TTL‑кэш; `/?force=1`
  - [ ] Redis/файловый кэш (опционально)
  - [ ] Параллельные запросы к нескольким аккаунтам Ozon

- Инфраструктура
  - [x] systemd + Nginx (reverse proxy)
  - [ ] systemd timers: регулярный refresh метрик
  - [ ] HTTPS (Let's Encrypt)

- Наблюдаемость
  - [ ] `/health` и `/metrics` (Prometheus)
  - [ ] Структурированные логи (info/warn/error)

---

## Полный гайд по проекту

### 1) Стек и требования
- Python 3.12, Flask 3, Gunicorn
- Nginx (reverse proxy)
- SQLite по умолчанию (можно Postgres через `DATABASE_URL`)

### 2) Установка и запуск (dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp -n .env.example .env  # затем заполните .env

# локальный запуск через Gunicorn
gunicorn --workers 2 --bind 127.0.0.1:8001 wsgi:app
# или простой тест
python wsgi.py
```
Откройте `http://127.0.0.1:8001/`.

### 3) Переменные окружения (.env)
Пример `.env` (лежит в `mp-dashboard/.env`):
```
# Wildberries
WB_API_TOKEN=...

# Ozon — несколько магазинов (FBO)
OZON_CLIENT_ID_1=...
OZON_API_KEY_1=...
OZON_SKUS_1=123,456,789

# Доп. магазины
OZON_CLIENT_ID_2=...
OZON_API_KEY_2=...
OZON_SKUS_2=...

TIMEZONE=Europe/Moscow
SECRET_KEY=change-me

# DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname
CACHE_TTL_SECONDS=600
```
Важно: `config.py` делает `load_dotenv(override=True)`, поэтому значения из `.env` перекрывают системные.

### 4) Продакшн: systemd + Nginx
Юнит `/etc/systemd/system/mp-dashboard.service`:
```
[Unit]
Description=MP Dashboard (Flask) via Gunicorn
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/mp-dashboard
EnvironmentFile=-/etc/mp-dashboard.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/root/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8001 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
Nginx (пример):
```
server {
    listen 80 default_server;
    server_name _;
    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8001;
    }
}
```
Команды:
```bash
systemctl enable --now mp-dashboard
systemctl status mp-dashboard --no-pager
journalctl -u mp-dashboard -f
nginx -t && systemctl reload nginx
```

### 5) Источники данных и устойчивость
- Wildberries Statistics API: `stocks`, `orders`, `sales` с полуночи.
- Ozon Seller API (FBO): `v1/analytics/stocks`, `posting fbo list (v3/v2)`, `v2/returns/fbo/list`, `v1/finance/cashbox/list`.
- Обработка ошибок:
  - WB 429: возвращаем данные из кэша (или нули) — карточка не ломается.
  - Ozon 404 на `returns`/`cashbox`: считаем пусто/0 и продолжаем.
  - В `routes/dashboard.py` части Ozon собираются независимо (stocks/today/balance).

### 6) Кэширование
In‑process TTL (`app/utils/cache.py`). Параметр `CACHE_TTL_SECONDS`. Принудительное обновление: `/?force=1`.

### 7) Алиасы и порядок SKU
`app/utils/sku_aliases.py`: `ALIAS_MAP` и `ALIAS_ORDER`. Сортировка учитывает порядок, затем имя.

### 8) Структура проекта (ключевое)
```
app/
  __init__.py
  models.py
  presenters.py
  routes/dashboard.py
  services/{wb_api.py, ozon_api.py}
  templates/{base.html, dashboard.html}
  static/js/app.js
config.py
wsgi.py
requirements.txt
README.md
```

### 9) Отладка
- `debug_ozon.py` — пример запроса к Ozon в контексте приложения.

### 10) Документация
- WB: https://dev.wildberries.ru/openapi/api-information
- Ozon: https://docs.ozon.ru/api/seller/
- В корне: `Документация Ozon Seller API.html`
