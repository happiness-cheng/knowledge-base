@echo off
echo Starting Knowledge Base...

:: Kill processes on our ports (more reliable than window title)
echo Cleaning up old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8766" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
ping -n 2 127.0.0.1 >nul

:: Start MySQL (XAMPP) if not running
echo Checking MySQL...
netstat -ano | findstr ":3306" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo Starting MySQL...
    start "" "D:\xampp\mysql\bin\mysqld.exe"
    :: Wait for MySQL to be ready (max 15 seconds)
    set /a tries=0
    :wait_mysql
    ping -n 2 127.0.0.1 >nul
    set /a tries+=1
    netstat -ano | findstr ":3306" | findstr "LISTENING" >nul 2>&1
    if %errorlevel% neq 0 (
        if %tries% lss 8 goto wait_mysql
        echo WARNING: MySQL may not have started properly
    ) else (
        echo MySQL is ready.
    )
) else (
    echo MySQL is already running.
)

echo.
echo Starting backend server...
cd backend
start "Backend" cmd /c "venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8766"

echo Starting frontend dev server...
cd ..\frontend
start "Frontend" cmd /c "npm run dev"

echo.
echo   MySQL:    localhost:3306
echo   Backend:  http://localhost:8766
echo   Frontend: http://localhost:5173
echo.

:: Open browser
start http://localhost:5173

echo Press any key to stop all servers...
pause > nul

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8766" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
