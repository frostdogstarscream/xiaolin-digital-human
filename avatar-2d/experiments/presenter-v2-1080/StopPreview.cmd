@echo off
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0preview_control.py" stop
if errorlevel 1 pause
