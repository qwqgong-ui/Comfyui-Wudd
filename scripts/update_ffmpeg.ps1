<#
.SYNOPSIS
Downloads a current Windows FFmpeg build into this custom node's local bin folder.

.DESCRIPTION
By default this script downloads BtbN's latest Windows x64 GPL autobuild zip,
extracts ffmpeg.exe, ffprobe.exe, and ffplay.exe, and copies them into ./bin.
The exe files remain ignored by Git.

.PARAMETER Url
Download URL for a zip archive that contains ffmpeg.exe, ffprobe.exe, and
ffplay.exe somewhere under it.

.PARAMETER Destination
Destination folder for the three FFmpeg executables. Defaults to ../bin relative
to this script.

.PARAMETER KeepArchive
Keep the downloaded zip and extracted temporary files.

.PARAMETER DryRun
Print what would happen without downloading or writing files.
#>

[CmdletBinding()]
param(
    [string]$Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    [string]$Destination,
    [switch]$KeepArchive,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $PSCommandPath
$RepoRoot = Split-Path -Parent $ScriptDir
if (-not $Destination) {
    $Destination = Join-Path $RepoRoot "bin"
}

$Destination = [System.IO.Path]::GetFullPath($Destination)
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("wudd_ffmpeg_" + [System.Guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path $TempRoot "ffmpeg.zip"
$ExtractDir = Join-Path $TempRoot "extract"
$RequiredFiles = @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")

Write-Host "FFmpeg source: $Url"
Write-Host "Destination:   $Destination"

if ($DryRun) {
    Write-Host "Dry run only; no files will be downloaded or changed."
    exit 0
}

New-Item -ItemType Directory -Force -Path $TempRoot, $ExtractDir, $Destination | Out-Null

try {
    Write-Host "Downloading FFmpeg archive..."
    Invoke-WebRequest -Uri $Url -OutFile $ArchivePath

    Write-Host "Extracting archive..."
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractDir -Force

    foreach ($FileName in $RequiredFiles) {
        $Match = Get-ChildItem -LiteralPath $ExtractDir -Recurse -Filter $FileName -File |
            Select-Object -First 1
        if (-not $Match) {
            throw "Archive did not contain $FileName"
        }

        $Target = Join-Path $Destination $FileName
        Copy-Item -LiteralPath $Match.FullName -Destination $Target -Force
        try {
            Unblock-File -LiteralPath $Target
        } catch {
            # Unblock-File may be unavailable or unnecessary on some systems.
        }
        Write-Host "Updated $Target"
    }

    $Ffmpeg = Join-Path $Destination "ffmpeg.exe"
    $VersionLine = & $Ffmpeg -version 2>$null | Select-Object -First 1
    if ($VersionLine) {
        Write-Host $VersionLine
    }
    Write-Host "Done. Restart ComfyUI to make sure nodes use the updated binary."
} finally {
    if (-not $KeepArchive -and (Test-Path -LiteralPath $TempRoot)) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    } elseif ($KeepArchive) {
        Write-Host "Kept temporary files at $TempRoot"
    }
}
