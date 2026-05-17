@echo off
echo Starting Knowledge Base...

:: Kill processes on our ports (more reliable than window title)
echo Cleaning up old processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
ping -n 3 127.0.0.1 >nul

echo.
echo Starting backend server...
cd backend
start "Backend" cmd /c "venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8765"

echo Starting frontend dev server...
cd ..\frontend
start "Frontend" cmd /c "npm run dev"

echo.
echo   Backend:  http://localhost:8765
echo   Frontend: http://localhost:5173
echo.

:: Open browser
start http://localhost:5173

echo Press any key to stop all servers...
pause > nul

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /F 2>nul
