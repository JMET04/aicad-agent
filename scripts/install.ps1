[CmdletBinding()]
param(
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root 'plugin\AiCadConstraint.bundle'
$pluginRoot = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins'
$destination = Join-Path $pluginRoot 'AiCadConstraint.bundle'
$appRoot = Join-Path $env:LOCALAPPDATA 'AiCadConstraint'
$runtime = Join-Path $appRoot 'runtime'
$jobs = Join-Path $appRoot 'jobs'

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Plugin bundle not found: $source"
}

function Test-Python {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    try {
        & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

if (-not $PythonPath) {
    $candidates = @()
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $localPython -PathType Container) {
        $candidates += Get-ChildItem -LiteralPath $localPython -Filter python.exe -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName
    }
    $PythonPath = $candidates | Where-Object { Test-Python $_ } | Select-Object -First 1
}
if (-not (Test-Python $PythonPath)) {
    throw 'Python 3.10+ was not found. Install 64-bit Python, or pass -PythonPath C:\path\python.exe.'
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$pythonw = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { $pythonw = $PythonPath }

New-Item -ItemType Directory -Path $pluginRoot, $destination, $runtime, $jobs -Force | Out-Null
Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
}

foreach ($name in @('src', 'tools', 'schema')) {
    $from = Join-Path $root $name
    $to = Join-Path $runtime $name
    New-Item -ItemType Directory -Path $to -Force | Out-Null
    Get-ChildItem -LiteralPath $from -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $to -Recurse -Force
    }
}

$runner = Join-Path $runtime 'tools\aicad.py'
[Environment]::SetEnvironmentVariable('AICAD_PYTHON', $PythonPath, 'User')
[Environment]::SetEnvironmentVariable('AICAD_PYTHONW', $pythonw, 'User')
[Environment]::SetEnvironmentVariable('AICAD_RUNNER', $runner, 'User')
[Environment]::SetEnvironmentVariable('AICAD_JOBS', $jobs, 'User')
$env:AICAD_PYTHON = $PythonPath
$env:AICAD_PYTHONW = $pythonw
$env:AICAD_RUNNER = $runner
$env:AICAD_JOBS = $jobs

& $PythonPath $runner doctor --json
if ($LASTEXITCODE -notin @(0, 3)) { throw 'Installed runtime failed its diagnostic check.' }

Write-Host "Installed plugin: $destination"
Write-Host "Installed runtime: $runtime"
Write-Host "Python: $PythonPath"
Write-Host 'Restart AutoCAD, then run AICAD_AI. Optional model setup: AICAD_SETUP.'
