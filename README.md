# MP Dashboard — Wildberries + Ozon (FBO)

Мини‑портал для мониторинга показателей по Wildberries и Ozon:
- Остатки на складах
- Заказано сегодня
- Выкуплено сегодня
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
  - Остатки FBO:  (основной), фоллбэки 
  - Заказы/выкупы FBO:  (фоллбэк )

## Алиасы SKU
 — алиасы и порядок отображения (Кронштейны → Карточки → Пакеты 8 → Пакеты 5 → Пакеты 2).

## Roadmap
- Графики продаж/выкупов
- Планировщик сбора метрик (systemd timer)
- Фильтры (склады, SKU, период)
- Управление алиасами/порядком через UI
- HTTPS (Let's Encrypt)
