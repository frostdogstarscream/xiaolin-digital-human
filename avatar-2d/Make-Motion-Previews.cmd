@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Make-Motion-Previews.ps1" %*
pause
