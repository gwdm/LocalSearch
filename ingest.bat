@echo off
REM LocalSearch - Run single Docker ingest pass
cd /d "%~dp0"
docker compose up -d qdrant
echo Waiting for Qdrant to be healthy...
:wait
docker compose ps qdrant | findstr "healthy" >nul 2>&1
if errorlevel 1 (
    timeout /t 5 /nobreak >nul
    goto :wait
)
echo Running ingest...
docker compose run --rm localsearch ingest
pause
