@echo off
:: 核心机制：利用 VBS 提权，静默获取 Administrator 权限，防止注入失败
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit

echo ==========================================
echo    AHU校园网无感连网工具 - 一键部署
echo                by: Colin
echo ==========================================

:: 交互式收集凭证
set /p acc="[1] 请输入校园网宽带账号 (如 E123123123@telecom): "
set /p pwd="[2] 请输入校园网密码: "

:: 物理隔离落地凭证
echo CAMPUS_ACCOUNT=%acc%> "%~dp0.env"
echo CAMPUS_PASSWORD=%pwd%>> "%~dp0.env"
echo [+] 本地凭证文件 .env 锻造完毕。

echo [+] 正在编译系统底层网络监听载荷...
set XML_FILE=%TEMP%\ahu_task.xml
(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<Triggers^>
echo     ^<EventTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Subscription^>^&lt;QueryList^&gt;^&lt;Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"^&gt;^&lt;Select Path="Microsoft-Windows-NetworkProfile/Operational"^&gt;*[System[Provider[@Name='Microsoft-Windows-NetworkProfile'] and EventID=10000]]^&lt;/Select^&gt;^&lt;/Query^&gt;^&lt;/QueryList^&gt;^</Subscription^>
echo     ^</EventTrigger^>
echo   ^</Triggers^>
echo   ^<Settings^>
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>
echo     ^<Hidden^>true^</Hidden^>
echo   ^</Settings^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>%~dp0login.exe^</Command^>
echo       ^<WorkingDirectory^>%~dp0^</WorkingDirectory^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%XML_FILE%"

echo [+] 正在向 Windows 内核注册 Event 10000 触发器...
schtasks /create /tn "AHU_AutoLogin" /xml "%XML_FILE%" /f

echo [+] 部署完成！工具已潜伏至系统后台，以后插上网线即可瞬间无感连网。
pause