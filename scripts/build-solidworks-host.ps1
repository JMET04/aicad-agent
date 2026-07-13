[CmdletBinding()]
param(
    [string]$Configuration = 'Release',
    [string]$OutputDirectory = 'build\solidworks-host'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$setup = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\SolidWorks\SolidWorks 2026\Setup' -ErrorAction SilentlyContinue
if (-not $setup.'SolidWorks Folder') { throw 'SolidWorks 2026 installation was not found.' }
$apiPath = Join-Path $setup.'SolidWorks Folder' 'api\redist'
foreach ($name in @('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $apiPath $name) -PathType Leaf)) { throw "SolidWorks interop is missing: $name" }
}
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) { throw 'Visual Studio Build Tools were not found.' }
$msbuild = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe | Select-Object -First 1
if (-not $msbuild) { throw 'MSBuild was not found.' }
$project = Join-Path $root 'solidworks-host\AiCad.SolidWorksHost\AiCad.SolidWorksHost.csproj'
& $msbuild $project /restore /t:Rebuild /p:Configuration=$Configuration "/p:SolidWorksApiPath=$apiPath" /nologo /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw 'SolidWorks host build failed.' }
$built = Join-Path (Split-Path -Parent $project) "bin\$Configuration"
$output = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Path $output -Force | Out-Null
Get-ChildItem -LiteralPath $built -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $output -Force }
Write-Host "SolidWorks host created: $output"
