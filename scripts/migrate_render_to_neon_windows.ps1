# CareerHunter — guarded one-time Windows Render Postgres -> Neon migration helper.
# Run locally only. Never paste database URLs into GitHub, CI, or a chat.
[CmdletBinding()]
param(
    [string]$BackupDirectory = (Join-Path $HOME "CareerHunterBackups"),
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-SecretText([string]$Label) {
    $secure = Read-Host -Prompt $Label -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Require-Tool([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required free command-line tool is not available: $Name"
    }
}

function Source-Parts([string]$Url) {
    try {
        $uri = [uri]$Url
        if ($uri.Scheme -notin @("postgres", "postgresql")) {
            throw "Source must be a PostgreSQL URL"
        }
        $split = $uri.UserInfo.Split(':', 2)
        if ($split.Count -ne 2 -or -not $uri.Host) {
            throw "Source URL has incomplete user/host information"
        }
        $database = [System.Net.WebUtility]::UrlDecode($uri.AbsolutePath.TrimStart('/'))
        if (-not $database) {
            throw "Source URL is missing database name"
        }
        return @{
            Host = $uri.Host
            Port = $(if ($uri.IsDefaultPort) { "5432" } else { [string]$uri.Port })
            User = [System.Net.WebUtility]::UrlDecode($split[0])
            Password = [System.Net.WebUtility]::UrlDecode($split[1])
            Database = $database
        }
    } catch {
        throw "Source URL is not a valid PostgreSQL connection URL"
    }
}

$sourceUrl = $null
$targetUrl = $null
$sourceParts = $null
$envKeys = @("PGPASSWORD", "PGSSLMODE", "DASHBOARD_DATABASE_URL", "NEON_DATABASE_URL")

try {
    Require-Tool "pg_dump"
    Require-Tool "pg_restore"
    Require-Tool "python"

    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $directory = [IO.Path]::GetFullPath($BackupDirectory)
    if ($directory.StartsWith($root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "Do not store private database backups in the public GitHub repository"
    }
    New-Item -ItemType Directory -Force -Path $directory | Out-Null

    $sourceUrl = Read-SecretText "Render external PostgreSQL connection URL (hidden)"
    $targetUrl = Read-SecretText "Neon PostgreSQL connection URL (hidden)"
    if (-not $sourceUrl -or -not $targetUrl) {
        throw "Both connection URLs are required"
    }
    $sourceParts = Source-Parts $sourceUrl

    $env:PGPASSWORD = $sourceParts.Password
    $env:PGSSLMODE = "require"
    $env:DASHBOARD_DATABASE_URL = $sourceUrl
    $env:NEON_DATABASE_URL = $targetUrl

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archive = Join-Path $directory "careerhunter-render-$stamp.dump"
    Write-Host "Creating a LOCAL private backup. No secrets or records are uploaded."
    & pg_dump --format=custom --no-owner --no-privileges --host $sourceParts.Host --port $sourceParts.Port --username $sourceParts.User --dbname $sourceParts.Database --file $archive
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $archive)) {
        throw "pg_dump failed; nothing will be copied to Neon"
    }
    if ((Get-Item $archive).Length -le 100) {
        throw "Backup archive is unexpectedly small"
    }
    & pg_restore --list $archive | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Backup archive could not be read; migration cancelled"
    }
    $checksum = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash
    Write-Host ("Private backup saved locally at: " + $archive)
    Write-Host ("SHA256: " + $checksum)
    Write-Host "Archive index checked; this is NOT an independent restore test."
    Write-Host "Keep this backup in a secure, encrypted location."

    Write-Host "Running read-only source/target preflight..."
    & python -m careerhunter.pg_transfer
    if ($LASTEXITCODE -ne 0) {
        throw "Database preflight failed; copy refused"
    }
    if ($PreflightOnly) {
        Write-Host "PREFLIGHT FINISHED. No Neon data copied."
        exit 0
    }

    Write-Host "Before copying, stop the live collector and verify no new writes are pending."
    Write-Host "The Render PostgreSQL source will NOT be deleted or switched."
    $approval = Read-Host "Type MIGRATE after verifying independent backup + maintenance window"
    if ($approval -cne "MIGRATE") {
        Write-Host "Copy cancelled. Backup remains available."
        exit 0
    }

    & python -m careerhunter.pg_transfer --apply --backup-confirmed
    if ($LASTEXITCODE -ne 0) {
        throw "Neon copy verification failed; production remains on Render"
    }
    Write-Host "Neon copy succeeded and was verified by the copy tool."
    Write-Host "Production still uses Render. Complete independent restore and smoke tests before cutover."
} finally {
    foreach ($key in $envKeys) {
        Remove-Item ("Env:" + $key) -ErrorAction SilentlyContinue
    }
    $sourceUrl = $null
    $targetUrl = $null
    $sourceParts = $null
}
