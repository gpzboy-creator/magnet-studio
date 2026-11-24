<# : MagnetStudio launcher for Windows - double-click it. (Lines up to "#>" are batch, the rest is PowerShell.)
@echo off
setlocal
set "MS_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:MS_SELF,[Text.Encoding]::UTF8); & ([ScriptBlock]::Create($s))"
set "RC=%errorlevel%"
if not "%RC%"=="0" pause
exit /b %RC%
#>

# Keeps a ready-made MagnetStudio next to this file (folder "MagnetStudio-app") and starts it.
# Every start: asks GitHub whether a newer build exists; if so, downloads it (~60 MB) and swaps it in.
# Offline (e.g. at an event): just starts the version that is already here.
# The repo is private, so a read-only GitHub token is needed. It is asked for once and saved
# encrypted for this Windows user (DPAPI) in %LOCALAPPDATA%\MagnetStudio\updater-token.dat.
# Your settings, templates and print counter live in your user folder and are never touched.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo      = 'gpzboy-creator/magnet-studio'
$AssetName = 'MagnetStudio-Windows.zip'
$Here      = Split-Path -Parent $env:MS_SELF
$AppRoot   = Join-Path $Here 'MagnetStudio-app'
$Exe       = Join-Path $AppRoot 'MagnetStudio\MagnetStudio.exe'
$Stamp     = Join-Path $AppRoot 'build-id.txt'
$TokenFile = Join-Path $env:LOCALAPPDATA 'MagnetStudio\updater-token.dat'
$TokenUrl  = 'https://github.com/settings/personal-access-tokens/new'
$Agent     = 'MagnetStudio-Updater'

function ConvertTo-Plain([Security.SecureString]$sec) {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

function Read-SavedToken {
    if ($env:MAGNETSTUDIO_UPDATER_TOKEN) { return $env:MAGNETSTUDIO_UPDATER_TOKEN }
    if (-not (Test-Path $TokenFile)) { return $null }
    try { return ConvertTo-Plain (Get-Content $TokenFile -Raw | ConvertTo-SecureString) } catch { return $null }
}

function Save-Token([string]$t) {
    if ($env:MAGNETSTUDIO_UPDATER_TOKEN) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path $TokenFile) | Out-Null
    ConvertTo-SecureString $t -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -Path $TokenFile
}

function Ask-Token {
    if ($env:MAGNETSTUDIO_UPDATER_TOKEN) { throw 'The token in MAGNETSTUDIO_UPDATER_TOKEN was refused.' }
    Write-Host ''
    Write-Host 'MagnetStudio needs a read-only GitHub key to download updates (one time only).'
    Write-Host "Opening $TokenUrl in your browser. There:"
    Write-Host '  Token name: MagnetStudio      Expiration: the longest offered'
    Write-Host '  Repository access: Only select repositories -> magnet-studio'
    Write-Host '  Permissions -> Repository permissions -> Contents: Read-only'
    Write-Host '  Generate token -> Copy'
    Start-Process $TokenUrl
    $t = (ConvertTo-Plain (Read-Host 'Paste the token here (it stays hidden) and press Enter' -AsSecureString)).Trim()
    if (-not $t) { throw 'No token entered.' }
    return $t
}

function Get-LatestRelease([string]$t) {
    $h = @{ Authorization = "Bearer $t"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
    Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/latest" -Headers $h -UserAgent $Agent -TimeoutSec 20
}

function Get-HttpCode($err) {
    try { return [int]$err.Exception.Response.StatusCode } catch { return 0 }
}

function Update-App {
    $tok = Read-SavedToken
    $asked = $false
    if (-not $tok) { $tok = Ask-Token; $asked = $true }
    try { $rel = Get-LatestRelease $tok }
    catch {
        $code = Get-HttpCode $_
        if ($code -in 401, 403, 404) {
            Write-Host "GitHub refused the key (HTTP $code) - it may be mistyped or expired. Let's make a new one."
            $tok = Ask-Token; $asked = $true
            $rel = Get-LatestRelease $tok
        } else { throw }
    }
    if ($asked) { Save-Token $tok; Write-Host 'Key saved.' }

    $asset = $rel.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
    if (-not $asset) { throw "The latest release has no $AssetName yet (a build may be running) - try again in a few minutes." }
    $have = if (Test-Path $Stamp) { (Get-Content $Stamp -Raw).Trim() } else { '' }
    if ("$($asset.id)" -eq $have) { Write-Host "MagnetStudio is up to date - $($rel.name)"; return }

    Write-Host "Downloading $($rel.name) ($([math]::Round($asset.size / 1MB)) MB)..."
    $zip = Join-Path $env:TEMP "MagnetStudio-$($asset.id).zip"
    Invoke-WebRequest -Uri $asset.url -Headers @{ Authorization = "Bearer $tok"; Accept = 'application/octet-stream' } `
        -UserAgent $Agent -OutFile $zip -TimeoutSec 900
    while (Get-Process -Name MagnetStudio -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path.StartsWith($AppRoot, [StringComparison]::OrdinalIgnoreCase) }) {
        Write-Host 'Close MagnetStudio to finish the update...'
        Start-Sleep -Seconds 3
    }
    $new = "$AppRoot.new"; $old = "$AppRoot.old"
    foreach ($d in $new, $old) { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }
    Write-Host 'Unpacking...'
    Expand-Archive -Path $zip -DestinationPath $new -Force
    if (-not (Test-Path (Join-Path $new 'MagnetStudio\MagnetStudio.exe'))) { throw 'The download looks incomplete - try again.' }
    if (Test-Path $AppRoot) { Rename-Item $AppRoot (Split-Path $old -Leaf) }
    Rename-Item $new (Split-Path $AppRoot -Leaf)
    Set-Content -Path $Stamp -Value $asset.id
    Remove-Item $old, $zip -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Updated to $($rel.name)"
}

try { Update-App }
catch {
    if (Test-Path $Exe) { Write-Warning "Could not check for updates ($($_.Exception.Message)) - starting the version you have." }
    else { Write-Host "Could not download MagnetStudio: $($_.Exception.Message)"; exit 1 }
}

Write-Host 'Starting MagnetStudio...'
if ($env:MAGNETSTUDIO_UPDATER_WAIT) { Start-Process -FilePath $Exe -Wait } else { Start-Process -FilePath $Exe }
