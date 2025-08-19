import sys
import os

# Добавляем путь к site-packages виртуального окружения
venv_path = os.path.join(os.path.dirname(__file__), '.venv', 'lib', 'python3.12', 'site-packages')
if venv_path not in sys.path:
    sys.path.insert(0, venv_path)

from app import create_app


app = create_app()


