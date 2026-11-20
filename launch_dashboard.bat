@echo off
setlocal
title AI Internship Application Agent - Dashboard Launcher


REM ============================================================================
REM AI INTERNSHIP APPLICATION AGENT - ONE-CLICK WINDOWS LAUNCHER
REM ============================================================================

cd /d "C:\Users\Asus\Downloads\AI-Internship-Agent"
if errorlevel 1 goto :err_dir

echo ============================================================================
echo   AI INTERNSHIP APPLICATION AGENT - WINDOWS DASHBOARD LAUNCHPAD
echo   Project Path: %CD%
echo ============================================================================
echo.

REM Ensure "AI Internship Agent.lnk" shortcut exists on the user's Windows Desktop
if not exist "AI Internship Agent.lnk" goto :skip_shortcut
if exist "%USERPROFILE%\Desktop" copy /Y "AI Internship Agent.lnk" "%USERPROFILE%\Desktop\AI Internship Agent.lnk" >nul 2>&1
if exist "%USERPROFILE%\OneDrive\Desktop" copy /Y "AI Internship Agent.lnk" "%USERPROFILE%\OneDrive\Desktop\AI Internship Agent.lnk" >nul 2>&1
:skip_shortcut

REM 1. Detect and select Python interpreter
set "PYTHON_EXE=python"

if not exist ".venv\Scripts\python.exe" goto :check_sys_py
".venv\Scripts\python.exe" -c "import streamlit" >nul 2>&1
if errorlevel 1 goto :venv_no_st
echo [INFO] Activating virtual environment (.venv)...
call ".venv\Scripts\activate.bat"
set "PYTHON_EXE=.venv\Scripts\python.exe"
goto :verify_py

:venv_no_st
echo [INFO] Virtual environment (.venv) detected; using system Python with pre-installed AI and Streamlit packages...

:check_sys_py
if not exist "C:\Python314\python.exe" goto :verify_py
"C:\Python314\python.exe" -c "import streamlit" >nul 2>&1
if not errorlevel 1 set "PYTHON_EXE=C:\Python314\python.exe"

:verify_py
REM 2. Verify Python is available
"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 goto :err_no_py

REM 3. Verify core dependencies
echo [INFO] Verifying Python and Streamlit dependencies...
"%PYTHON_EXE%" -c "import streamlit, pandas, openpyxl, pymupdf, docx, sklearn, playwright, pydantic, dotenv" >nul 2>&1
if errorlevel 1 goto :err_missing_deps
echo [OK] All required dependencies verified.
echo.

REM 4. Prevent duplicate Streamlit instances on port 8501
netstat -ano | findstr /R /C:":8501 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto :already_running

REM 5. Launch app.py using Streamlit and open in default browser
echo [INFO] Launching AI Internship Application Agent Dashboard on http://localhost:8501 ...
start "" "http://localhost:8501"
"%PYTHON_EXE%" -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
if errorlevel 1 goto :err_streamlit
goto :eof

:already_running
echo [INFO] AI Internship Agent Dashboard is already running on http://localhost:8501
echo [INFO] Opening existing dashboard in your default browser...
start "" "http://localhost:8501"
goto :eof

:err_dir
echo [ERROR] Could not switch to project directory: C:\Users\Asus\Downloads\AI-Internship-Agent
pause
exit /b 1

:err_no_py
echo [ERROR] Python is not installed or not found on PATH.
echo Please install Python 3.11+ and run: python -m pip install -r requirements.txt
pause
exit /b 1

:err_missing_deps
echo [ERROR] One or more required Python dependencies are missing.
echo Run the following command to install them:
echo     "%PYTHON_EXE%" -m pip install -r requirements.txt
pause
exit /b 1

:err_streamlit
echo.
echo [ERROR] Streamlit exited unexpectedly. Check logs\agent.log for details.
pause
exit /b 1
