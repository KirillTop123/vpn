@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Первый запуск: ставлю зависимости, это займёт пару минут...
  py -3 -m venv .venv || (echo Не найден Python 3.11+. Установите его с python.org и поставьте галочку "Add to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt || (pause & exit /b 1)
  .venv\Scripts\python -m playwright install chromium
)
start "" .venv\Scripts\pythonw app.py
