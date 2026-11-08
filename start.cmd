@echo off
cd /d "%~dp0"
if exist "%~dp0.venv-scopy\Scripts\pythonw.exe" (
  start "" "%~dp0.venv-scopy\Scripts\pythonw.exe" "%~dp0desktop.py"
  goto end
)
where pyw >nul 2>nul
if errorlevel 1 goto fallback
start "" pyw -3 "%~dp0desktop.py"
goto end
:fallback
python desktop.py
:end
if errorlevel 1 pause
