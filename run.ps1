$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "未找到项目虚拟环境。请先在项目目录执行：powershell -ExecutionPolicy Bypass -File .\setup.ps1"
}

Set-Location -LiteralPath $projectRoot
& $venvPython app.py
