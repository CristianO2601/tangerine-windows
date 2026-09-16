# ---------------------------------------------------------------------------
# Tangerine for Windows - one-shot packaging script (no admin required).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Steps:
#   1. ensure PyInstaller is installed for the current Python
#   2. build the onedir/windowed bundle: dist\Tangerine\
#   3. create dist\Tangerine-<version>-windows-portable.zip
#   4. if Inno Setup 6 (ISCC.exe) is available, compile
#      dist\Tangerine-<version>-Setup.exe
# ---------------------------------------------------------------------------
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $RepoRoot "dist"
$SpecRel = "packaging\tangerine.spec"
$SpecFile = Join-Path $PSScriptRoot "tangerine.spec"
$IssFile = Join-Path $PSScriptRoot "installer.iss"
$PathsFile = Join-Path $RepoRoot "tangerine\paths.py"
$BundleDir = Join-Path $DistDir "Tangerine"
$BundleExe = Join-Path $BundleDir "Tangerine.exe"

function Get-AppVersion {
    param([Parameter(Mandatory = $true)][string]$PathsFile)
    $pattern = '^\s*APP_VERSION\s*=\s*[''"]\s*([^''"\s]+)'
    $match = Select-String -LiteralPath $PathsFile -Pattern $pattern | Select-Object -First 1
    if (-not $match) {
        throw "Could not read APP_VERSION from $PathsFile"
    }
    return $match.Matches[0].Groups[1].Value
}

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N1} KB' -f ($Bytes / 1KB)) }
    return "$Bytes B"
}

function Find-Iscc {
    $candidates = @()
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $onPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $null
}

try {
    $Version = Get-AppVersion -PathsFile $PathsFile
    Write-Host "==> Tangerine for Windows $Version" -ForegroundColor Cyan

    Write-Host "==> [1/4] Ensuring PyInstaller is installed"
    & $Python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }

    Write-Host "==> [2/4] Building frozen bundle (onedir, windowed)"
    Push-Location -LiteralPath $RepoRoot
    try {
        & $Python -m PyInstaller --noconfirm --clean $SpecRel
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $BundleExe)) {
        throw "Expected frozen executable not found: $BundleExe"
    }

    Write-Host "==> [3/4] Creating portable archive"
    $PortableZip = Join-Path $DistDir "Tangerine-$Version-windows-portable.zip"
    if (Test-Path -LiteralPath $PortableZip) { Remove-Item -LiteralPath $PortableZip -Force }
    Compress-Archive -Path (Join-Path $BundleDir "*") -DestinationPath $PortableZip -CompressionLevel Optimal
    if (-not (Test-Path -LiteralPath $PortableZip)) {
        throw "Portable archive was not created: $PortableZip"
    }

    $Installer = Join-Path $DistDir "Tangerine-$Version-Setup.exe"
    $Iscc = $null
    if (-not $SkipInstaller) {
        Write-Host "==> [4/4] Building installer with Inno Setup 6"
        $Iscc = Find-Iscc
    }

    if ($SkipInstaller) {
        Write-Warning "Installer build skipped (-SkipInstaller)."
    }
    elseif (-not $Iscc) {
        Write-Warning "ISCC.exe (Inno Setup 6) not found - installer not built."
        Write-Warning "Install it with: winget install --id JRSoftware.InnoSetup -e"
        Write-Warning "Then re-run: ISCC.exe /DAPPVER=$Version `"$IssFile`""
    }
    else {
        Write-Host "    Using: $Iscc"
        if (Test-Path -LiteralPath $Installer) { Remove-Item -LiteralPath $Installer -Force }
        & $Iscc "/DAPPVER=$Version" $IssFile
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
        if (-not (Test-Path -LiteralPath $Installer)) {
            throw "Setup executable was not created: $Installer"
        }
    }

    Write-Host ""
    Write-Host "================= Tangerine build summary =================" -ForegroundColor Cyan
    Write-Host ("Version       : {0}" -f $Version)
    Write-Host ("Frozen bundle : {0}" -f $BundleDir)
    $exeItem = Get-Item -LiteralPath $BundleExe
    Write-Host ("  Tangerine.exe : {0}" -f (Format-Size $exeItem.Length))
    $zipItem = Get-Item -LiteralPath $PortableZip
    Write-Host ("Portable zip  : {0} ({1})" -f $PortableZip, (Format-Size $zipItem.Length))
    if (Test-Path -LiteralPath $Installer) {
        $setupItem = Get-Item -LiteralPath $Installer
        Write-Host ("Installer     : {0} ({1})" -f $Installer, (Format-Size $setupItem.Length))
    }
    else {
        Write-Host "Installer     : not built (ISCC.exe unavailable or skipped)"
    }
    Write-Host "===========================================================" -ForegroundColor Cyan
}
catch {
    Write-Host ""
    Write-Host ("BUILD FAILED: {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}

exit 0
