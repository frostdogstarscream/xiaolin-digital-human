@echo off
if not exist "%~dp0outputs\motion-review-v3\motion-sequence.mp4" (
  echo Motion review video is missing.
  pause
  exit /b 1
)
start "" "%~dp0outputs\motion-review-v3\motion-sequence.mp4"
