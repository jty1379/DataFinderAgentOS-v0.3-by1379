$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3 -m venv (Join-Path $projectRoot "venv")
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --index-url "https://pypi.org/simple" -r (Join-Path $projectRoot "requirements.txt")

$crawlSetup = Join-Path $projectRoot "venv\Scripts\crawl4ai-setup.exe"
if (Test-Path -LiteralPath $crawlSetup) {
    & $crawlSetup
} else {
    & $venvPython -m playwright install chromium
}

Write-Host "虚拟环境与 Crawl4AI 已准备完成。" -ForegroundColor Green
