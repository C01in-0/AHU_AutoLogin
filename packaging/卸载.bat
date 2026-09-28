@echo off
chcp 65001 >nul
call "%~dp0程序文件\uninstall.bat"
exit /b %errorlevel%
