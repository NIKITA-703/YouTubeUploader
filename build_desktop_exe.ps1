param(
    [switch]$OneDir,
    [switch]$Console
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$EntryPoint = Join-Path $RepoRoot "desktop_app.py"
$DistRoot = Join-Path $RepoRoot "dist"
$BuildRoot = Join-Path $RepoRoot "build"
$AppName = "YouTubeUploaderDesktop"
$AppDistDir = Join-Path $DistRoot $AppName
$ProfileTemplateSource = Join-Path $RepoRoot "data\json\desktop_app_profile.json"
$RequirementsPath = Join-Path $RepoRoot "requiments.txt"
$BundledFfmpegDir = $null

function Test-PythonModule {
    param([string]$ModuleName)
    & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)"
    return $LASTEXITCODE -eq 0
}

function Resolve-FfmpegDir {
    $candidates = @()
    if ($env:FFMPEG_DIR) {
        $candidates += $env:FFMPEG_DIR
    }
    $candidates += @(
        (Join-Path $RepoRoot "tools\ffmpeg\bin"),
        (Join-Path $RepoRoot "ffmpeg\bin"),
        (Join-Path $RepoRoot "bin")
    )

    foreach ($dir in $candidates) {
        if (-not $dir) { continue }
        $ffmpeg = Join-Path $dir "ffmpeg.exe"
        $ffprobe = Join-Path $dir "ffprobe.exe"
        if ((Test-Path $ffmpeg) -and (Test-Path $ffprobe)) {
            return (Resolve-Path $dir).Path
        }
    }

    return $null
}

if (-not (Test-Path $EntryPoint)) {
    throw "Entry point not found: $EntryPoint"
}

$RequiredModules = @("customtkinter", "librosa", "yt_dlp")
$MissingModules = @($RequiredModules | Where-Object { -not (Test-PythonModule $_) })
if ($MissingModules.Count -gt 0 -and (Test-Path $RequirementsPath)) {
    Write-Host "Installing missing project dependencies: $($MissingModules -join ', ')"
    & $Python -m pip install -r $RequirementsPath pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
} elseif (-not (Test-PythonModule "PyInstaller")) {
    Write-Host "Installing PyInstaller into the active environment..."
    & $Python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller installation failed."
    }
}

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", $AppName,
    "--paths", $RepoRoot,
    "--add-data", "$RepoRoot\data\montage;data\montage",
    "--collect-all", "customtkinter"
)

$BundledFfmpegDir = Resolve-FfmpegDir
if ($BundledFfmpegDir) {
    $PyInstallerArgs += @(
        "--add-binary", "$BundledFfmpegDir\ffmpeg.exe;bin",
        "--add-binary", "$BundledFfmpegDir\ffprobe.exe;bin"
    )
}

if ($OneDir) {
    $PyInstallerArgs += "--onedir"
} else {
    $PyInstallerArgs += "--onefile"
}

if ($Console) {
    $PyInstallerArgs += "--console"
} else {
    $PyInstallerArgs += "--windowed"
}

if (Test-PythonModule "librosa") {
    $PyInstallerArgs += @("--collect-submodules", "librosa")
}

if (Test-PythonModule "yt_dlp") {
    $PyInstallerArgs += @("--collect-submodules", "yt_dlp")
}

$PyInstallerArgs += $EntryPoint

if (Test-Path $AppDistDir) {
    Remove-Item -LiteralPath $AppDistDir -Recurse -Force
}

$BuildAppDir = Join-Path $BuildRoot $AppName
if (Test-Path $BuildAppDir) {
    Remove-Item -LiteralPath $BuildAppDir -Recurse -Force
}

Write-Host "Building desktop app..."
& $Python @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if ($OneDir -and -not (Test-Path $AppDistDir)) {
    New-Item -ItemType Directory -Path $AppDistDir | Out-Null
}

if ($OneDir) {
    $ProfileTemplateTarget = Join-Path $AppDistDir "data\json\desktop_app_profile.json"
} else {
    $ProfileTemplateTarget = Join-Path $DistRoot "data\json\desktop_app_profile.json"
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProfileTemplateTarget) | Out-Null
Copy-Item -LiteralPath $ProfileTemplateSource -Destination $ProfileTemplateTarget -Force

Write-Host ""
Write-Host "Desktop build ready:"
if ($OneDir) {
    Write-Host "  EXE folder: $AppDistDir"
} else {
    Write-Host "  EXE file:   $(Join-Path $DistRoot ($AppName + '.exe'))"
    Write-Host "  Config dir: $(Join-Path $DistRoot 'data')"
}
Write-Host ""
Write-Host "Bundled inside build:"
Write-Host "  - data/montage assets (Frame/Sub/voice tags/fonts if present)"
if ($BundledFfmpegDir) {
    Write-Host "  - ffmpeg.exe and ffprobe.exe from $BundledFfmpegDir"
}
Write-Host ""
Write-Host "Left external next to the build:"
Write-Host "  - data/json/desktop_app_profile.json"
Write-Host ""
if (-not $BundledFfmpegDir) {
    Write-Host "Still required on the target machine:"
    Write-Host "  - ffmpeg and ffprobe in PATH, or ship them next to the .exe / in bin"
}
Write-Host "Optional on the target machine:"
Write-Host "  - JS runtime for yt-dlp only if a specific YouTube source requires it (node/deno/bun)"
