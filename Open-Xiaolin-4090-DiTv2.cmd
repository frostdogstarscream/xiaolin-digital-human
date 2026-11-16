@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-Xiaolin-4090-DiTv2.ps1"
if errorlevel 1 pause
