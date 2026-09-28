$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\install.ps1') -LibraryOnly
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$definitions = Get-TaskDefinitions 'C:\AHU & Test\AutoLogin'
foreach ($name in $definitions.Keys) {
    # An in-memory task object only; never register, start or delete a task.
    $definition = $service.NewTask(0)
    $definition.XmlText = $definitions[$name]
    if ($definition.Principal.UserId -notin @('SYSTEM', 'S-1-5-18')) { throw 'Wrong principal' }
    Write-Host "XML accepted: $name"
}
