@echo off
REM LocalSearch - Open web dashboard (Docker)
cd /d "%~dp0"
echo Starting Docker services...
docker compose up -d
echo.
echo Dashboard: http://localhost:8080
echo Qdrant:    http://localhost:6333/dashboard
echo.
echo Opening browser...
start http://localhost:8080
echo.
echo Press any key to view logs, or Ctrl+C to exit.
pause >nul
docker compose logs -f localsearch
