param([string]$Python = "$PSScriptRoot\..\.venv\Scripts\python.exe")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath "$PSScriptRoot\..").Path
$originalBuildPath = $env:PATH
Push-Location -LiteralPath $projectRoot
try {
    # Resolve system ICU from Windows, not an unrelated toolchain (e.g. Poppler) in PATH.
    $pythonBaseDirectory = & $Python -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Python installation' }
    $env:PATH = "$projectRoot\.venv\Scripts;$pythonBaseDirectory;$env:SystemRoot\System32;$env:SystemRoot"
    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name CodexBridge --paths src --copy-metadata keyring --collect-submodules keyring.backends --hidden-import keyring.backends.Windows --exclude-module keyring.testing --exclude-module pytest --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtPdf scripts/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    & $Python scripts/collect_licenses.py dist/CodexBridge
    if ($LASTEXITCODE -ne 0) { throw 'License text collection failed' }
    Write-Host "Build: $projectRoot\dist\CodexBridge\CodexBridge.exe"
} finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
