[CmdletBinding()]
param(
    [string]$SourceDirectory,
    [string]$ExpectedVersion = '1.16.0'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $SourceDirectory) {
    $candidates = @(
        (Join-Path $repositoryRoot 'release\v1.16.0\aicad-agent'),
        (Join-Path $repositoryRoot 'plugins\aicad-agent')
    )
    foreach ($candidate in $candidates) {
        $candidatePluginPath = Join-Path $candidate '.codex-plugin\plugin.json'
        $candidateIntegrationPath = Join-Path $candidate 'integration-manifest.json'
        if (
            (Test-Path -LiteralPath $candidatePluginPath -PathType Leaf) -and
            (Test-Path -LiteralPath $candidateIntegrationPath -PathType Leaf)
        ) {
            $candidatePlugin = Get-Content -LiteralPath $candidatePluginPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $candidateIntegration = Get-Content -LiteralPath $candidateIntegrationPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (
                [string]$candidatePlugin.version -eq $ExpectedVersion -and
                [string]$candidateIntegration.version -eq $ExpectedVersion
            ) {
                $SourceDirectory = $candidate
                break
            }
        }
    }
    if (-not $SourceDirectory) {
        throw "No built and manifest-bound aicad-agent $ExpectedVersion directory was found. Build and verify release\v$ExpectedVersion first."
    }
}
$source = [IO.Path]::GetFullPath($SourceDirectory)
$pluginsRoot = [IO.Path]::GetFullPath((Join-Path $HOME 'plugins'))
$destination = Join-Path $pluginsRoot 'aicad-agent'
$marketplacePath = [IO.Path]::GetFullPath((Join-Path $HOME '.agents\plugins\marketplace.json'))

$sourcePluginPath = Join-Path $source '.codex-plugin\plugin.json'
$sourceIntegrationPath = Join-Path $source 'integration-manifest.json'
if (-not (Test-Path -LiteralPath $sourcePluginPath -PathType Leaf)) {
    throw "Built aicad-agent plugin was not found: $source"
}
if (-not (Test-Path -LiteralPath $sourceIntegrationPath -PathType Leaf)) {
    throw "Verified integration manifest was not found: $sourceIntegrationPath"
}
$sourcePlugin = Get-Content -LiteralPath $sourcePluginPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceIntegration = Get-Content -LiteralPath $sourceIntegrationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$sourcePlugin.version -ne $ExpectedVersion -or [string]$sourceIntegration.version -ne $ExpectedVersion) {
    throw "Refusing to install version mismatch: expected $ExpectedVersion, plugin=$($sourcePlugin.version), integration=$($sourceIntegration.version)"
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.10+ must be available as the python command for the MCP server.' }
& $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'aicad-agent requires Python 3.10 or newer.' }
$verifier = Join-Path $repositoryRoot 'scripts\verify_release_package.py'
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
    throw "Release verifier was not found: $verifier"
}
& $python.Source -B $verifier $source --source-root $repositoryRoot --expected-version $ExpectedVersion
if ($LASTEXITCODE -ne 0) { throw "Source package verification failed; installation was not started: $source" }
New-Item -ItemType Directory -Path $pluginsRoot -Force | Out-Null
if (Test-Path -LiteralPath $destination) {
    $resolved = (Resolve-Path -LiteralPath $destination).Path
    if (-not $resolved.StartsWith($pluginsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace plugin outside personal plugins: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
$sourceIntegrityPath = $sourceIntegrationPath
$sourceIntegrity = $sourceIntegration
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
if ([string]$installedManifest.version -ne $ExpectedVersion) {
    throw "Installed manifest version mismatch: expected $ExpectedVersion, got $($installedManifest.version)"
}

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
