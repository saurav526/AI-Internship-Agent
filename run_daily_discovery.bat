@echo off
setlocal
title AI Internship Agent - Daily 09:00 AM IST Discovery Task

cd /d "C:\Users\Asus\Downloads\AI-Internship-Agent"
if errorlevel 1 exit /b 1

if not exist "logs" mkdir "logs"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import pydantic, sklearn, pymupdf, docx" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=C:\Users\Asus\Downloads\AI-Internship-Agent\.venv\Scripts\python.exe"
)

if "%PYTHON_EXE%"=="python" (
    if exist "C:\Python314\python.exe" set "PYTHON_EXE=C:\Python314\python.exe"
)

echo [%DATE% %TIME%] Starting Scheduled Daily Internship Discovery using %PYTHON_EXE% >> "logs\task_scheduler_runner.log"
"%PYTHON_EXE%" -m src.daily_automation >> "logs\task_scheduler_runner.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] Completed Scheduled Daily Internship Discovery with exit code %EXIT_CODE% >> "logs\task_scheduler_runner.log"

exit /b %EXIT_CODE%

