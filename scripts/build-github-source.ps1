[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release\v1.2.2\github-repository',
    [string]$Version = '1.2.2',
    [string]$PluginArchive = 'release\v1.2.2\aicad-agent-1.2.2.zip'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $root 'release'))
$target = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
if (-not $target.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Source staging must stay inside release: $target"
}
if (Test-Path -LiteralPath $target) {
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolved.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear source staging outside release: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
New-Item -ItemType Directory -Path $target -Force | Out-Null

$rootFiles = @('README.md', 'pyproject.toml', '.gitignore')
foreach ($item in $rootFiles) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination $target -Force
}
foreach ($item in @('CHANGELOG.md', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md')) {
    Copy-Item -LiteralPath (Join-Path $root "agent-plugin\aicad-agent\$item") -Destination $target -Force
}
Copy-Item -LiteralPath (Join-Path $root 'agent-plugin\aicad-agent\LICENSE') -Destination $target -Force

foreach ($item in @('.github', 'src', 'schema', 'examples', 'prompts', 'docs', 'plugin', 'agent-plugin', 'scripts', 'tests', 'tools')) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination $target -Recurse -Force
}

$solidWorksTarget = Join-Path $target 'solidworks-host\AiCad.SolidWorksHost'
New-Item -ItemType Directory -Path $solidWorksTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'solidworks-host\AiCad.SolidWorksHost\Program.cs') -Destination $solidWorksTarget -Force
Copy-Item -LiteralPath (Join-Path $root 'solidworks-host\AiCad.SolidWorksHost\AiCad.SolidWorksHost.csproj') -Destination $solidWorksTarget -Force

$dist = Join-Path $target 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$archive = [IO.Path]::GetFullPath((Join-Path $root $PluginArchive))
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw "Plugin archive is missing: $archive"
}
Copy-Item -LiteralPath $archive -Destination $dist -Force

$resolvedTarget = (Resolve-Path -LiteralPath $target).Path
Get-ChildItem -LiteralPath $target -Directory -Recurse -Force |
    Where-Object Name -In @('__pycache__', '.pytest_cache', 'bin', 'obj') |
    Sort-Object FullName -Descending |
    ForEach-Object {
        $candidate = (Resolve-Path -LiteralPath $_.FullName).Path
        if (-not $candidate.StartsWith($resolvedTarget + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove generated directory outside staging: $candidate"
        }
        Remove-Item -LiteralPath $candidate -Recurse -Force
    }
Get-ChildItem -LiteralPath $target -File -Recurse -Force |
    Where-Object Extension -In @('.pyc', '.pyo') |
    Remove-Item -Force

$archiveName = Split-Path -Leaf $archive
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $dist $archiveName)).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    (Join-Path $dist 'SHA256SUMS'),
    "$archiveHash  $archiveName`n",
    [Text.UTF8Encoding]::new($false)
)

$files = @(Get-ChildItem -LiteralPath $target -Recurse -File | Where-Object Name -ne 'source-manifest.json')
$entries = @($files | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($resolvedTarget.Length).TrimStart('\').Replace('\', '/')
        size = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    }
})
$manifest = [ordered]@{
    schema = 'aicad_agent_source_release_v1'
    name = 'aicad-agent'
    version = $Version
    repository = 'https://github.com/JMET04/aicad-agent'
    visibilityDefault = 'private'
    releaseStatus = 'engineering-candidate'
    apiKeyRequired = $false
    proprietaryDependenciesRedistributed = $false
    safetyLocks = [ordered]@{
        reviewOnly = $true
        accepted = $false
        ruleEnabled = $false
        packagingGated = $true
        comparativeSuperiorityClaimAllowed = $false
    }
    excluded = @('jobs', 'research/paper/experiments', 'build outputs', 'native customer drawings', 'personal paths', 'credentials', 'caches', 'SolidWorks interop binaries')
    files = $entries
}
[IO.File]::WriteAllText(
    (Join-Path $target 'source-manifest.json'),
    ($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

Write-Host "GitHub source staging created: $target"

