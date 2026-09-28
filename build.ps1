param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Python regression failed' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/test_installer.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Installer regression failed' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/validate_task_xml.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Task Scheduler XML validation failed' }
    & $Python -m PyInstaller --clean --noconfirm --noconsole --onefile --version-file version_info.txt --name login login.pyw
    if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
    & $Python package.py
    if ($LASTEXITCODE -ne 0) { throw 'Package assembly failed' }
} finally { Pop-Location }
