param([string]$PythonPath = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))

$ErrorActionPreference = 'Stop'
$originalBuildPath = $env:PATH
$originalBuildCache = $env:PYINSTALLER_CONFIG_DIR
Push-Location -LiteralPath $PSScriptRoot
try {
    $basePythonDirectory = & $PythonPath -c "import sys; print(sys.base_prefix)"
    if ($LASTEXITCODE -ne 0) { throw '无法读取 Python 环境，请检查 PythonPath。' }
    $pythonScriptsDirectory = Split-Path -Parent $PythonPath
    $env:PATH = ($pythonScriptsDirectory, $basePythonDirectory, (Join-Path $env:WINDIR 'System32'), $env:WINDIR) -join ';'
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build-cache'
    & $PythonPath -m PyInstaller --noconfirm --clean UAV_WarGame.spec
    if ($LASTEXITCODE -ne 0) { throw 'Windows 程序构建失败。' }
    Write-Output '构建完成：dist\UAV_WarGame.exe'
} finally {
    $env:PATH = $originalBuildPath
    $env:PYINSTALLER_CONFIG_DIR = $originalBuildCache
    Pop-Location
}
