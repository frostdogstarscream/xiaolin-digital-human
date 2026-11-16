@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Preview-Girl008.ps1" -SkipImport
if errorlevel 1 pause
