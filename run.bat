@echo off
REM LocalSearch Docker launcher
REM Usage: run.bat <mode> [options]
REM   run.bat            - Start everything (ingest loop + web UI)
REM   run.bat ingest     - Run single ingest pass
REM   run.bat web        - Start web UI only
REM   run.bat shell      - Drop into container shell
REM   run.bat logs       - Follow container logs
REM   run.bat stop       - Stop all containers

cd /d "%~dp0"

if "%~1"=="" (
    echo Starting all services (ingest loop + web UI)...
    docker compose up -d
    echo.
    echo Web UI:  http://localhost:8080
    echo Qdrant:  http://localhost:6333/dashboard
    echo.
    echo View logs: docker compose logs -f localsearch
    goto :eof
)

if /i "%~1"=="ingest" (
    echo Running single ingest pass...
    docker compose run --rm localsearch ingest
    goto :eof
)

if /i "%~1"=="web" (
    echo Starting web UI only...
    docker compose up -d qdrant
    docker compose run --rm -d -p 8080:8080 localsearch web
    goto :eof
)

if /i "%~1"=="shell" (
    echo Dropping into container shell...
    docker compose run --rm localsearch shell
    goto :eof
)

if /i "%~1"=="logs" (
    docker compose logs -f localsearch
    goto :eof
)

if /i "%~1"=="stop" (
    echo Stopping all containers...
    docker compose down
    goto :eof
)

echo Usage: run.bat [ingest^|web^|shell^|logs^|stop]
echo   (no args)  Start everything (ingest loop + web UI)
echo   ingest     Run single ingest pass then exit
echo   web        Start web UI only
echo   shell      Drop into container shell
echo   logs       Follow container logs
echo   stop       Stop all containers
