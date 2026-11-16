@echo off
"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0preview_control.py" start
if errorlevel 1 pause
