@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || (echo Не найден Python 3.11+. & pause & exit /b 1)
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt pyinstaller || (pause & exit /b 1)
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --name SborshikBaz ^
  --add-data "ui;ui" --add-data "data;data" ^
  --collect-all playwright --collect-submodules uvicorn --collect-submodules webview ^
  app.py || (pause & exit /b 1)
echo.
echo Готово: dist\SborshikBaz.exe
pause
