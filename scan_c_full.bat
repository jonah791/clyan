@echo off
echo Clyan Full C: Scan — Requesting Administrator Privileges...
echo.
powershell -Command "Start-Process python3 -ArgumentList '-m clyan scan disk --full --top_n 30' -Verb RunAs -Wait"
echo.
echo Done. Check the admin window for results.
pause
