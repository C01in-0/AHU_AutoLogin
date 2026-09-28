@echo off
chcp 65001 >nul
call "%~dp0程序文件\install.bat"
exit /b %errorlevel%
