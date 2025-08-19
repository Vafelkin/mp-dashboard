from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def get_timeout_to_next_half_hour(*args, **kwargs):
    """
    Вычисляет количество секунд до следующего полного или получасового часа.
    Используется как динамический таймаут для Flask-Caching.
    Функция должна принимать *args и **kwargs, так как декоратор
    передает в нее аргументы декорируемой функции.
    """
    # Явно используем московское время для всех расчетов
    tz = ZoneInfo("Europe/Moscow")
    now = datetime.now(tz)
    
    if now.minute < 30:
        next_run = now.replace(minute=30, second=0, microsecond=0)
    else:
        next_run = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    
    timeout = (next_run - now).total_seconds()
    # Возвращаем 0, если таймаут отрицательный (на всякий случай)
    return max(0, int(timeout))
