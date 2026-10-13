@echo off
chcp 65001 >nul
title MeetingScribe V1.2 - Cai dat
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto :use_python
py -3.11 -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 goto :use_launcher
set "PYCMD=py -3.11"
goto :install
:use_launcher
set "PYCMD=py -3"
goto :install
:use_python
set "PYCMD=python"
:install
echo [1/3] Tao moi truong Python (khuyen nghi Python 3.11 64-bit)...
%PYCMD% -m venv .venv
if errorlevel 1 goto :error
echo [2/3] Cap nhat pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
echo [3/3] Cai thu vien. Can Internet lan dau...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Cai dat xong. Chay START_WINDOWS.bat de mo ung dung.
pause
exit /b 0
:error
echo.
echo CAI DAT THAT BAI. Kiem tra Python va Internet, xem thong bao phia tren.
pause
exit /b 1
