@echo off
chcp 65001 >nul
title MeetingScribe V1.2 - Server
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Chua cai dat. Hay chay setup_windows.bat truoc.
 pause
 exit /b 1
)
echo Dang khoi dong MeetingScribe tren may cua ban...
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
