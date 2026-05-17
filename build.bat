@echo off
echo ========================================
echo  Knowledge Base - Desktop App Builder
echo ========================================
echo.

echo [1/3] Building frontend...
cd frontend
call npx vite build
if errorlevel 1 (
    echo ERROR: Frontend build failed!
    pause
    exit /b 1
)
cd ..

echo.
echo [2/3] Packaging with PyInstaller...
cd backend
call venv\Scripts\pyinstaller.exe knowledge_base.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: Packaging failed!
    pause
    exit /b 1
)
cd ..

echo.
echo [3/3] Setup data directory...
if not exist "backend\dist\KnowledgeBase\data" mkdir "backend\dist\KnowledgeBase\data"
if not exist "backend\dist\KnowledgeBase\data\uploads" mkdir "backend\dist\KnowledgeBase\data\uploads"

echo.
echo ========================================
echo  Build complete!
echo.
echo  App: backend\dist\KnowledgeBase\KnowledgeBase.exe
echo  Size:
for %%A in ("backend\dist\KnowledgeBase\KnowledgeBase.exe") do echo   %%~zA bytes
echo ========================================
echo.
pause
