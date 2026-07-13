[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$PurgeSettings
)

$ErrorActionPreference = 'Stop'
$destination = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\AiCadConstraint.bundle'))
$appRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'AiCadConstraint'))
$expectedPluginRoot = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins'))
$expectedLocalRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA)

if (-not $destination.StartsWith($expectedPluginRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove unexpected plugin path: $destination"
}
if (-not $appRoot.StartsWith($expectedLocalRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove unexpected runtime path: $appRoot"
}

foreach ($path in @($destination, $appRoot)) {
    if (Test-Path -LiteralPath $path -PathType Container) {
        if ($PSCmdlet.ShouldProcess($path, 'Remove AI CAD Constraint component')) {
            Remove-Item -LiteralPath $path -Recurse -Force
            Write-Host "Removed: $path"
        }
    }
}
foreach ($name in @('AICAD_PYTHON', 'AICAD_PYTHONW', 'AICAD_RUNNER', 'AICAD_JOBS')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'User')
}

if ($PurgeSettings) {
    $settings = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'AiCadConstraint'))
    if (-not $settings.StartsWith([IO.Path]::GetFullPath($env:APPDATA) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected settings path: $settings"
    }
    if (Test-Path -LiteralPath $settings -PathType Container) { Remove-Item -LiteralPath $settings -Recurse -Force }
    cmdkey.exe /delete:AiCadConstraint/OpenAI 2>$null | Out-Null
}

Write-Host 'Uninstalled. Restart AutoCAD to clear the current process environment.'
