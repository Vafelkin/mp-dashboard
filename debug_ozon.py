import os
import sys
from pprint import pprint
import requests

# Добавляем корневую директорию проекта в путь поиска модулей
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app
from app.services.ozon_api import _headers

# Создаем экземпляр приложения для доступа к конфигурации
app = create_app()

# Выполняем в контексте приложения
with app.app_context():
    print(">>> Запрашиваю список статусов отправлений Ozon...")
    
    # Получаем аккаунты из конфигурации
    ozon_accounts = app.config.get('OZON_ACCOUNTS', [])
    
    if not ozon_accounts:
        print("!!! Не найдены аккаунты Ozon в конфигурации. Проверьте .env файл.")
    else:
        try:
            # Берем данные первого аккаунта для запроса
            account = ozon_accounts[0]
            client_id = account["client_id"]
            api_key = account["api_key"]
            
            resp = requests.post(
                "https://api-seller.ozon.ru/v1/status/list",
                headers=_headers(client_id, api_key),
                json={},
                timeout=30
            )
            resp.raise_for_status()
            
            print("\n✅ Список статусов FBO:")
            pprint(resp.json())
            
        except Exception as e:
            print(f"\n❌ Произошла ошибка при вызове функции: {e}")
            import traceback
            traceback.print_exc()
