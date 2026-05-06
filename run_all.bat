@echo off
TITLE MachineWhisperer Launcher
echo ============================================================
echo           MachineWhisperer - Full System Launcher
echo ============================================================
echo.
echo   NOTE: AWS credentials are configured in backend/.env
echo.

:: Kill old processes
echo [1] Cleaning up old processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul
timeout /t 2 /nobreak >nul

:: Start Machine Simulator FIRST (Backend depends on it)
echo [2] Starting Machine Simulator (port 9000)...
start "MachineSimulator" cmd /k "echo STARTING SIMULATOR... & cd /d "%~dp0machine_simulator" & "%~dp0venv\Scripts\python.exe" server.py"
timeout /t 3 /nobreak >nul

:: Start Backend (connects to simulator on port 9000)
echo [3] Starting Backend (port 8000)...
start "MachineWhisperer-Backend" cmd /k "echo STARTING BACKEND... & cd /d "%~dp0backend" & "%~dp0venv\Scripts\python.exe" main.py"
timeout /t 3 /nobreak >nul

:: Start Frontend
echo [4] Starting Frontend (port 5174)...
start "MachineWhisperer-Frontend" cmd /k "echo STARTING FRONTEND... & cd /d "%~dp0Frontend" & npm run dev"

echo.
echo [5] Waiting for frontend to compile...
timeout /t 8 /nobreak >nul

:: Open both UIs
echo [6] Opening Browser...
start http://localhost:9000
start http://localhost:5174

echo.
echo ============================================================
echo   SYSTEM RUNNING:
echo     Simulator UI:   http://localhost:9000  (adjust sliders)
echo     Dashboard:      http://localhost:5174  (view analytics)
echo     Backend API:    http://localhost:8000  (data + ML)
echo ============================================================
echo.
echo   The simulator feeds live data to the backend.
echo   Move sliders in the Simulator to see changes in Dashboard.
echo.
echo   Press any key to STOP all services.
echo ============================================================
pause

:: Cleanup on exit
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul
echo All services stopped.
