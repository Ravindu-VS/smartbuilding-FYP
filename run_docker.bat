@echo off
echo ===================================================
echo   Smart Building Enterprise Platform - Docker Mode
echo ===================================================
echo.
echo Ensuring Docker is ready...
echo (If Docker is not open, this will fail. Please open Docker Desktop first.)
echo.
docker-compose up -d --build
echo.
echo [INFO] Enterprise WSO2 Architecture launched!
echo [NOTE] The 3D Twin Dashboard is running on http://localhost:3001
echo.
pause
