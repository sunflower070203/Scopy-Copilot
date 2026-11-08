@echo off
cd /d "%~dp0"
py -3 server.py --open
if errorlevel 1 pause
