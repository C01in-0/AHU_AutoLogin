$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[ERROR] Right-click uninstall.bat and choose Run as administrator.'
    exit 1
}
$failed = @()
foreach ($name in @('AHU_AutoLogin','AHU_AutoLogin_Delay','AHU_AutoLogin_OnLogon','AHU_AutoLogin_OnStart','AHU_AutoLogin_KeepAlive')) {
    try {
        if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
        }
        if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'Task still exists' }
        Write-Host "[OK] Removed or absent: $name"
    } catch { $failed += $name; Write-Host "[ERROR] Could not remove: $name" }
}
Write-Host 'Files, credentials and separately configured proxy-cleanup tasks were kept.'
if ($failed.Count) { exit 1 }
exit 0
