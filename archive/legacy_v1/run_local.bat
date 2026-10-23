@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ===================================================================
rem  Smart Building digital twin - starts everything on this PC:
rem    1. Edge brain   (python raspberry_pi\edge_brain.py, port 8001)
rem    2. 3D dashboard (Next.js, port 3000) and opens it in the browser
rem  Optional: "run_local.bat test" also starts the ESP32 TEST SENDER
rem  (fake readings, shown on the dashboard as TEST SENDER, never as the board).
rem ===================================================================
cd /d "%~dp0"

rem Use the venv's python.exe directly: activate.bat still points to the
rem folder the venv was created in, so "activate" can pick the wrong Python.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python venv not found at %PY%
  echo Create it:  py -3.13 -m venv .venv
  echo then:       .venv\Scripts\python.exe -m pip install -r raspberry_pi\requirements.txt
  pause & exit /b 1
)
"%PY%" -c "import flask, sklearn, pandas, joblib" 2>nul
if errorlevel 1 (
  echo Python packages missing. Installing raspberry_pi\requirements.txt ...
  "%PY%" -m pip install -r raspberry_pi\requirements.txt || (pause & exit /b 1)
)
if not exist "dashboard\fyp-research-twin\node_modules" (
  echo Installing dashboard packages ^(first run only^)...
  pushd dashboard\fyp-research-twin
  call npm install || (popd & pause & exit /b 1)
  popd
)

rem An old Edge Brain or dashboard still running keeps its port, and the new one
rem then cannot start (the browser would show the old one). Offer to stop it.
for %%P in (8001 3000) do (
  set "PIDS="
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do set "PIDS=!PIDS! %%a"
  if defined PIDS (
    echo Port %%P is already in use by process!PIDS! ^(probably an old Edge Brain or dashboard window^).
    choice /c YN /m "Stop it now"
    if errorlevel 2 (
      echo Close that window, then run this again.
      pause & exit /b 1
    )
    for %%k in (!PIDS!) do taskkill /PID %%k /F >nul 2>&1
    timeout /t 1 /nobreak >nul
  )
)

echo [1/3] Starting the edge brain on port 8001...
start "Edge Brain - port 8001" cmd /k ".venv\Scripts\python.exe raspberry_pi\edge_brain.py"

echo [2/3] Starting the 3D dashboard on port 3000...
start "3D Digital Twin - port 3000" /d "%~dp0dashboard\fyp-research-twin" cmd /k "npm run dev"

if /i "%~1"=="test" (
  echo       Starting the ESP32 TEST SENDER ^(not the real board^)...
  start "ESP32 TEST SENDER - not the real board" cmd /k "timeout /t 5 /nobreak >nul & .venv\Scripts\python.exe raspberry_pi\esp32_test_sender.py"
)

echo [3/3] Waiting for both to be ready...
set /a tries=0
:wait
set /a tries+=1
curl -s -o nul http://127.0.0.1:8001/health && curl -s -o nul http://127.0.0.1:3000/ && goto ready
if !tries! geq 90 goto ready
timeout /t 1 /nobreak >nul
goto wait
:ready
start "" http://localhost:3000

echo.
echo ===================================================
echo   Dashboard:       http://localhost:3000
echo   Edge brain:      http://127.0.0.1:8001/health
echo   ESP32 must POST to http://THIS-PC-IP:8001/api/hardware/sensor-data
echo   This PC's IPv4 address(es):
ipconfig | findstr /c:"IPv4"
echo   (set server_url in the firmware to one of these; same Wi-Fi as the board)
echo   Close the two server windows to stop everything.
echo ===================================================
pause
