@echo off
echo ===================================================
echo   Smart Building Cyber-Physical Platform
echo   Raspberry Pi Edge Brain (Development Mode)
echo ===================================================
echo.
echo [1/3] Starting Edge Intelligence Brain (Port 8001)...
start "Edge Brain" cmd /k ".\.venv\Scripts\activate && python raspberry_pi\edge_brain.py"

echo [2/3] Starting Next.js 3D WebGL Digital Twin Dashboard...
start "3D Digital Twin Frontend" cmd /k "cd dashboard\fyp-research-twin && npm run dev"

echo [3/3] Waiting for servers to initialize...
timeout /t 3 /nobreak >nul

echo Opening 3D Twin Dashboard in default browser: http://localhost:3000
start http://localhost:3000

echo.
echo ===================================================
echo   Full System Successfully Launched!
echo   - Edge Brain API: http://127.0.0.1:8001
echo   - 3D Digital Twin: http://localhost:3000
echo   - ESP32 endpoint:  POST http://127.0.0.1:8001/api/hardware/sensor-data
echo   - SSE stream:      GET  http://127.0.0.1:8001/api/stream
echo ===================================================
echo.
pause
