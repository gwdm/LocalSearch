@echo off
REM LocalSearch launcher - uses Miniconda3 env "312" (Python 3.12.8)
REM Usage: run.bat <command> [options]
REM   run.bat ingest          - Start ingestion pipeline
REM   run.bat dashboard       - Open live GUI dashboard
REM   run.bat search "query"  - Semantic search

set PYTHON=%USERPROFILE%\Miniconda3\envs\312\python.exe

if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    echo Please ensure Miniconda3 env "312" is installed.
    pause
    exit /b 1
)

cd /d "%~dp0"
"%PYTHON%" -m localsearch.cli %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo Process exited with error code %ERRORLEVEL%
    pause
)
