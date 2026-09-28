@echo off
cd /d "%~dp0"
start "" /wait "%~dp0login.exe" --probe
set "result=%errorlevel%"
powershell.exe -NoProfile -Command "Get-Content -LiteralPath 'autologin.log' -Tail 12 | Select-String 'selected ip=|exit code=' | Select-Object -Last 2"
pause
exit /b %result%
