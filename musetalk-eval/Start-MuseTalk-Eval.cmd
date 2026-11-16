@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-MuseTalk-Eval.ps1" -OpenBrowser
if errorlevel 1 pause
