param([switch]$LibraryOnly)
$ErrorActionPreference = 'Stop'

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-TaskXml {
    param([string]$Directory, [string]$Trigger, [int]$DelaySeconds)
    $exe = [Security.SecurityElement]::Escape((Join-Path $Directory 'login.exe'))
    $dir = [Security.SecurityElement]::Escape($Directory)
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Colin</Author><Description>AHU AutoLogin v1.2</Description></RegistrationInfo>
  <Triggers>$Trigger</Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><Enabled>true</Enabled><Hidden>true</Hidden><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT2M</ExecutionTimeLimit></Settings>
  <Actions Context="System"><Exec><Command>$exe</Command><Arguments>--delay $DelaySeconds</Arguments><WorkingDirectory>$dir</WorkingDirectory></Exec></Actions>
</Task>
"@
}

function Get-TaskDefinitions {
    param([string]$Directory)
    $event = '<EventTrigger><Enabled>true</Enabled><Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"&gt;&lt;Select Path="Microsoft-Windows-NetworkProfile/Operational"&gt;*[System[Provider[@Name=''Microsoft-Windows-NetworkProfile''] and EventID=10000]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription></EventTrigger>'
    $weekly = '<CalendarTrigger><StartBoundary>2026-01-05T09:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday /></DaysOfWeek></ScheduleByWeek></CalendarTrigger>'
    return [ordered]@{
        AHU_AutoLogin = (New-TaskXml $Directory $event 0)
        AHU_AutoLogin_Delay = (New-TaskXml $Directory $event 15)
        AHU_AutoLogin_OnLogon = (New-TaskXml $Directory '<LogonTrigger><Enabled>true</Enabled></LogonTrigger>' 20)
        AHU_AutoLogin_OnStart = (New-TaskXml $Directory '<BootTrigger><Enabled>true</Enabled></BootTrigger>' 30)
        AHU_AutoLogin_KeepAlive = (New-TaskXml $Directory $weekly 0)
    }
}

function Ensure-Config {
    param([string]$Directory)
    $path = Join-Path $Directory '.env'
    if (Test-Path -LiteralPath $path) {
        $lines = [IO.File]::ReadAllLines($path)
        if (-not ($lines -match '^\s*CAMPUS_ACCOUNT\s*=\s*\S') -or -not ($lines -match '^\s*CAMPUS_PASSWORD\s*=\s*\S')) {
            throw 'Existing .env is incomplete. Please check it locally; it has not been overwritten.'
        }
        Write-Host '[OK] Keeping existing .env, including custom settings.'
        return
    }
    # If unpacked into a new directory, migrate from the existing main task.
    $oldTask = Get-ScheduledTask -TaskName 'AHU_AutoLogin' -TaskPath '\' -ErrorAction SilentlyContinue
    if ($oldTask) {
        foreach ($action in $oldTask.Actions) {
            $oldExe = ([string]$action.Execute).Trim('"')
            if (-not [IO.Path]::IsPathRooted($oldExe)) { continue }
            $oldDir = Split-Path -Parent $oldExe
            $oldConfig = Join-Path $oldDir '.env'
            if (Test-Path -LiteralPath $oldConfig) {
                Copy-Item -LiteralPath $oldConfig -Destination $path
                Ensure-Config $Directory
                return
            }
        }
    }
    $account = Read-Host 'Campus account'
    $secure = Read-Host 'Campus password' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ([string]::IsNullOrWhiteSpace($account) -or [string]::IsNullOrWhiteSpace($password)) { throw 'Account/password cannot be empty.' }
    [IO.File]::WriteAllLines($path, @("CAMPUS_ACCOUNT=$account", "CAMPUS_PASSWORD=$password", 'CAMPUS_IP_PREFIXES=10.,172.16.,172.21.'), [Text.UTF8Encoding]::new($false))
    $password = $null
}

function Update-Tasks {
    param($Definitions)
    $old = @{}
    # Capture all previous definitions before changing any task.
    foreach ($name in $Definitions.Keys) {
        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        $old[$name] = if ($task) { Export-ScheduledTask -TaskName $name -TaskPath '\' } else { $null }
    }
    $touched = [Collections.Generic.List[string]]::new()
    try {
        foreach ($name in $Definitions.Keys) {
            $touched.Add($name)
            Register-ScheduledTask -TaskName $name -TaskPath '\' -Xml $Definitions[$name] -Force | Out-Null
            Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop | Out-Null
        }
    } catch {
        $failure = $_
        foreach ($name in $touched) {
            try {
                if ($old[$name]) { Register-ScheduledTask -TaskName $name -TaskPath '\' -Xml $old[$name] -Force | Out-Null }
                elseif (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) {
                    Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
                }
            } catch { Write-Warning "Could not restore task: $name. Re-run the previous installer." }
        }
        throw $failure
    }
}

if ($LibraryOnly) { return }
try {
    if (-not (Test-Admin)) { throw 'Right-click install.bat and choose Run as administrator.' }
    $directory = $PSScriptRoot
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'login.exe'))) { throw 'login.exe is missing. Extract the complete ZIP first.' }
    Write-Host 'AHU AutoLogin v1.2 | Author: Colin'
    Ensure-Config $directory
    & wevtutil.exe sl 'Microsoft-Windows-NetworkProfile/Operational' /e:true
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable NetworkProfile event log; existing tasks were not changed.' }
    Update-Tasks (Get-TaskDefinitions $directory)
    Write-Host '[OK] Five tasks installed. Existing proxy-cleanup tasks were preserved.'
    Start-ScheduledTask -TaskName 'AHU_AutoLogin' -TaskPath '\'
    Write-Host '[OK] Authentication requested. This is not a login-success check.'
    Write-Host "See $directory\autologin.log for authenticated/already_online or the failure status."
    exit 0
} catch { Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
