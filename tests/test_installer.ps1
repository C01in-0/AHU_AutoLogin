$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\install.ps1') -LibraryOnly
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
$definitions = Get-TaskDefinitions 'C:\AHU & 中文\AutoLogin'
Assert ($definitions.Count -eq 5) 'Expected five original task names'
$delays = @(0,15,20,30,0)
$position = 0
foreach ($name in $definitions.Keys) {
    [xml]$xml = $definitions[$name]
    Assert ($xml.Task.Actions.Exec.Command -eq 'C:\AHU & 中文\AutoLogin\login.exe') 'Path escaping changed'
    Assert ($xml.Task.Actions.Exec.Arguments -eq "--delay $($delays[$position])") 'Delay changed'
    Assert ($xml.Task.Settings.WakeToRun -eq 'false') 'Must not wake PC'
    Assert ($xml.Task.Settings.DisallowStartIfOnBatteries -eq 'false') 'Battery behavior changed'
    Assert ($xml.Task.Principals.Principal.UserId -eq 'S-1-5-18') 'Must run as SYSTEM'
    if ($name -like '*KeepAlive') {
        Assert ($xml.Task.Triggers.CalendarTrigger.StartBoundary -like '*T09:00:00') 'Weekly time changed'
        Assert ($xml.Task.Triggers.CalendarTrigger.ScheduleByWeek.DaysOfWeek.InnerXml -match 'Monday') 'Weekly day changed'
    }
    $position++
}
[xml]$eventXml = ([xml]$definitions['AHU_AutoLogin']).Task.Triggers.EventTrigger.Subscription
Assert ($eventXml.QueryList.Query.Select.InnerText -match 'EventID=10000') 'Network event changed'

# Task store is an in-memory dictionary; never call real Task Scheduler mutations.
$script:store = @{}
$script:failName = ''
$script:failedOnce = $false
function Get-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction)
    if ($script:store.ContainsKey($TaskName)) { return [pscustomobject]@{TaskName=$TaskName; Actions=@()} }
}
function Export-ScheduledTask { param($TaskName,$TaskPath) return $script:store[$TaskName] }
function Register-ScheduledTask { param($TaskName,$TaskPath,$Xml,[switch]$Force)
    # Simulate failure after a partial mutation, so rollback must include the failing item.
    $script:store[$TaskName] = $Xml
    if ($TaskName -eq $script:failName -and -not $script:failedOnce) {
        $script:failedOnce = $true
        throw 'Synthetic creation failure'
    }
}
function Unregister-ScheduledTask { param($TaskName,$TaskPath,$Confirm) $script:store.Remove($TaskName) }
foreach ($mode in @('upgrade','fresh')) {
    foreach ($failure in $definitions.Keys) {
        $script:store = @{'UnrelatedTask'='keep'; 'Clear_User_Proxy_On_Logon'='keep-proxy'}
        if ($mode -eq 'upgrade') { foreach ($name in $definitions.Keys) { $script:store[$name] = "old-$name" } }
        $before = $script:store.Clone()
        $script:failName = $failure
        $script:failedOnce = $false
        try { Update-Tasks $definitions; throw 'Expected injected failure' } catch {
            Assert ($_.Exception.Message -eq 'Synthetic creation failure') 'Unexpected exception'
        }
        Assert ($script:store.Count -eq $before.Count) 'Rollback count mismatch'
        foreach ($name in $before.Keys) { Assert ($script:store[$name] -eq $before[$name]) "Rollback lost $name" }
    }
}
$script:failName = ''
Update-Tasks $definitions
Assert ($script:store['Clear_User_Proxy_On_Logon'] -eq 'keep-proxy') 'Proxy task changed'

$fixture = Join-Path $PSScriptRoot ('fixture-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $fixture | Out-Null
try {
    $config = Join-Path $fixture '.env'
    [IO.File]::WriteAllText($config, "CAMPUS_ACCOUNT=FAKE`r`nCAMPUS_PASSWORD=FAKE`r`nCAMPUS_IP_PREFIXES=172.22.`r`nCUSTOM=keep`r`n", [Text.UTF8Encoding]::new($false))
    $beforeHash = (Get-FileHash -LiteralPath $config).Hash
    Ensure-Config $fixture
    Assert ((Get-FileHash -LiteralPath $config).Hash -eq $beforeHash) 'Existing config bytes changed'
} finally {
    # Only files created above; no recursive cleanup.
    Remove-Item -LiteralPath (Join-Path $fixture '.env')
    Remove-Item -LiteralPath $fixture
}
Write-Host 'PASS: five task XMLs, ten failure/rollback scenarios, proxy preservation, exact config preservation.'
