param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ArchiveName = "零界-齐语林-瞭望与问数系统v0.3源码.zip"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path.TrimEnd('\', '/')
$ArchiveRoot = "DataFinderAgentOS"
$OutputDirectory = Split-Path -Parent $ProjectRoot
$OutputPath = Join-Path $OutputDirectory $ArchiveName

$ExcludedDirectories = @(
    "venv",
    ".venv",
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    ".playwright-cli",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "playwright-report",
    "test-results",
    "node_modules"
)

function Convert-ToArchivePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ($Path -replace '\\', '/').TrimStart('/')
}

function Test-ExcludedPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = Convert-ToArchivePath $RelativePath
    $segments = $normalized.Split('/', [System.StringSplitOptions]::RemoveEmptyEntries)
    foreach ($segment in $segments) {
        if ($ExcludedDirectories -contains $segment.ToLowerInvariant()) {
            return $true
        }
    }

    $fileName = [System.IO.Path]::GetFileName($normalized)
    $lowerName = $fileName.ToLowerInvariant()

    if ($normalized -match '(?i)^database/.+\.(db|sqlite|sqlite3)(-shm|-wal)?$') { return $true }
    if ($normalized -match '(?i)^database/.+\.(db-shm|db-wal)$') { return $true }
    if ($normalized -match '(?i)^config/(runtime_secret\.txt|runtime_model_secrets\.json|model_secrets\.json)$') { return $true }
    if ($normalized -match '(?i)(^|/)\.env($|\.)') { return $true }
    if ($normalized -match '(?i)(^|/)(screenshots|videos|traces)/') { return $true }
    if ($normalized -match '(?i)^data/dgUser/[0-9]+/') { return $true }
    if ($lowerName -match '\.(pyc|pyo|log|map|tmp|bak|key)$') { return $true }
    if ($lowerName -match '\.trace\.zip$') { return $true }
    if ($lowerName -match '\.zip$') { return $true }
    if ($lowerName -in @('.coverage', 'coverage.xml', '.ds_store', 'thumbs.db')) { return $true }

    return $false
}

function Test-TextForSecrets {
    param([Parameter(Mandatory = $true)][System.IO.FileInfo]$File)

    $textExtensions = @(
        '.py', '.html', '.htm', '.js', '.css', '.md', '.txt', '.json',
        '.yaml', '.yml', '.toml', '.ini', '.cfg', '.ps1'
    )
    if ($textExtensions -notcontains $File.Extension.ToLowerInvariant()) {
        return
    }

    $content = [System.IO.File]::ReadAllText($File.FullName)
    $secretPatterns = @(
        '(?i)sk-(?!test|example|demo)[a-z0-9_-]{20,}',
        '(?i)\bBDUSS\s*=',
        '(?i)\bCookie\s*:\s*[^\r\n]{20,}',
        '(?i)\bOPENAI_API_KEY\s*=\s*["'']?[a-z0-9_-]{16,}',
        '(?i)\bDATAFINDER_COOKIE_SECRET\s*=\s*["'']?[a-z0-9_-]{16,}'
    )
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            throw "敏感内容扫描失败：$($File.FullName) 命中 $pattern"
        }
    }
}

$AllFiles = Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Force -File
$FilesToPack = [System.Collections.Generic.List[System.IO.FileInfo]]::new()

foreach ($file in $AllFiles) {
    $relative = $file.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/')
    if (Test-ExcludedPath $relative) {
        continue
    }
    Test-TextForSecrets $file
    $FilesToPack.Add($file)
}

$requiredEntries = @('app.py', 'README.md', 'requirements.txt')
foreach ($required in $requiredEntries) {
    if (-not ($FilesToPack | Where-Object {
        $_.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/') -eq $required
    })) {
        throw "缺少必须文件：$required"
    }
}

# 只删除本作业的固定输出文件，绝不使用通配符，不触碰其他组参考 ZIP。
if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$archive = [System.IO.Compression.ZipFile]::Open(
    $OutputPath,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    foreach ($file in ($FilesToPack | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/')
        $entryName = "$ArchiveRoot/$(Convert-ToArchivePath $relative)"
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
}

$validationArchive = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
try {
    $entryNames = @($validationArchive.Entries | ForEach-Object { $_.FullName })
    foreach ($entryName in $entryNames) {
        if (-not $entryName.StartsWith("$ArchiveRoot/", [System.StringComparison]::Ordinal)) {
            throw "ZIP 根目录错误：$entryName"
        }
        $relative = $entryName.Substring($ArchiveRoot.Length + 1)
        if (Test-ExcludedPath $relative) {
            throw "ZIP 禁入扫描失败：$entryName"
        }
    }
    foreach ($required in $requiredEntries) {
        if ($entryNames -notcontains "$ArchiveRoot/$required") {
            throw "ZIP 缺少必须文件：$ArchiveRoot/$required"
        }
    }
}
finally {
    $validationArchive.Dispose()
}

$size = (Get-Item -LiteralPath $OutputPath).Length
Write-Host "打包完成：$OutputPath"
Write-Host "文件数量：$($FilesToPack.Count)"
Write-Host ("ZIP 大小：{0:N0} bytes" -f $size)
Write-Host "禁入扫描：通过"
