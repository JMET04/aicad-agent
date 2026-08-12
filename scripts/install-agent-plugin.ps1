[CmdletBinding()]
param(
    [string]$SourceDirectory
)

$ErrorActionPreference = 'Stop'
if (-not $SourceDirectory) {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $candidates = @(
        (Join-Path $repositoryRoot 'plugins\aicad-agent'),
        (Join-Path $repositoryRoot 'release\v1.10.1\aicad-agent'),
        (Join-Path $repositoryRoot 'agent-plugin\aicad-agent')
    )
    $SourceDirectory = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ '.codex-plugin\plugin.json') -PathType Leaf } | Select-Object -First 1
    if (-not $SourceDirectory) { throw 'No built or source aicad-agent plugin directory was found.' }
}
$source = [IO.Path]::GetFullPath($SourceDirectory)
$pluginsRoot = [IO.Path]::GetFullPath((Join-Path $HOME 'plugins'))
$destination = Join-Path $pluginsRoot 'aicad-agent'
$marketplacePath = [IO.Path]::GetFullPath((Join-Path $HOME '.agents\plugins\marketplace.json'))

if (-not (Test-Path -LiteralPath (Join-Path $source '.codex-plugin\plugin.json') -PathType Leaf)) {
    throw "Built aicad-agent plugin was not found: $source"
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.10+ must be available as the python command for the MCP server.' }
& $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'aicad-agent requires Python 3.10 or newer.' }
New-Item -ItemType Directory -Path $pluginsRoot -Force | Out-Null
if (Test-Path -LiteralPath $destination) {
    $resolved = (Resolve-Path -LiteralPath $destination).Path
    if (-not $resolved.StartsWith($pluginsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace plugin outside personal plugins: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
$sourceIntegrityPath = Join-Path $source 'integration-manifest.json'
if (-not (Test-Path -LiteralPath $sourceIntegrityPath -PathType Leaf)) {
    throw "Verified integration manifest was not found: $sourceIntegrityPath"
}
$sourceIntegrity = Get-Content -LiteralPath $sourceIntegrityPath -Raw -Encoding UTF8 | ConvertFrom-Json
$declaredFiles = @($sourceIntegrity.files)
if ($declaredFiles.Count -eq 0) { throw 'Integration manifest declares no payload files.' }

New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($item in $declaredFiles) {
    $relative = [string]$item.path
    $normalizedRelative = $relative.Replace('\\', '/')
    if ([IO.Path]::IsPathRooted($relative) -or $normalizedRelative.Split('/') -contains '..') {
        throw "Unsafe integration-manifest path: $relative"
    }
    $sourceFile = [IO.Path]::GetFullPath((Join-Path $source $normalizedRelative))
    $destinationFile = [IO.Path]::GetFullPath((Join-Path $destination $normalizedRelative))
    if (-not $sourceFile.StartsWith($source + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Source payload escaped plugin root: $relative"
    }
    if (-not $destinationFile.StartsWith($destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed payload escaped plugin root: $relative"
    }
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { throw "Manifest payload is missing: $relative" }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destinationFile) -Force | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
}
foreach ($supplemental in @('integration-manifest.json', 'SHA256SUMS')) {
    Copy-Item -LiteralPath (Join-Path $source $supplemental) -Destination (Join-Path $destination $supplemental) -Force
}

$installedManifestPath = Join-Path $destination '.codex-plugin\plugin.json'
$installedManifest = Get-Content -LiteralPath $installedManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

$marketplaceDirectory = Split-Path -Parent $marketplacePath
New-Item -ItemType Directory -Path $marketplaceDirectory -Force | Out-Null
if (Test-Path -LiteralPath $marketplacePath -PathType Leaf) {
    $marketplace = Get-Content -LiteralPath $marketplacePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $marketplace.name) { throw 'Existing personal marketplace has no name.' }
    if (-not $marketplace.interface) { $marketplace | Add-Member -NotePropertyName interface -NotePropertyValue ([pscustomobject]@{ displayName = 'Personal' }) }
    if (-not $marketplace.plugins) { $marketplace | Add-Member -NotePropertyName plugins -NotePropertyValue @() }
} else {
    $marketplace = [pscustomobject]@{ name = 'personal'; interface = [pscustomobject]@{ displayName = 'Personal' }; plugins = @() }
}
$entry = [pscustomobject]@{
    name = 'aicad-agent'
    source = [pscustomobject]@{ source = 'local'; path = './plugins/aicad-agent' }
    policy = [pscustomobject]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
    category = 'Developer Tools'
}
$marketplace.plugins = @($marketplace.plugins | Where-Object name -ne 'aicad-agent') + @($entry)
$json = $marketplace | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText($marketplacePath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

Write-Host "Installed agent plugin source: $destination"
Write-Host "Installed plugin version: $($installedManifest.version)"
Write-Host "Updated personal marketplace: $marketplacePath"
Write-Host 'Open the plugin in Codex and install it, then start a new task to load its skill and MCP tools.'
