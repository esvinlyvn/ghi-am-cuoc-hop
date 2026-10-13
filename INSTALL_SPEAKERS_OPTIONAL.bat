@echo off
chcp 65001 >nul
title MeetingScribe - Cai nhan dien nguoi noi
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Hay chay setup_windows.bat truoc.
 pause
 exit /b 1
)
echo Pyannote la tien ich tuy chon de phan biet nhieu nguoi noi trong cung kenh.
echo Can Internet, tai khoan Hugging Face va chap nhan dieu khoan model Community-1.
".venv\Scripts\python.exe" -m pip install "pyannote.audio>=4,<5"
pause
