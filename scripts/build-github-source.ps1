[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release\v1.11.1\github-repository',
    [string]$Version = '1.11.1',
    [string]$PluginArchive = 'release\v1.11.1\aicad-agent-1.11.1.zip',
    [string]$PluginDirectory = 'release\v1.11.1\aicad-agent'
)

$ErrorActionPreference = 'Stop'

function Convert-TreeTextToLf {
    param([Parameter(Mandatory = $true)][string]$TreeRoot)
    $textExtensions = @('.aicad', '.cjs', '.cs', '.csproj', '.css', '.dxf', '.html', '.js', '.json', '.lsp', '.md', '.mjs', '.ps1', '.py', '.scr', '.svg', '.toml', '.txt', '.xml', '.yaml', '.yml')
    $textNames = @('.gitattributes', '.gitignore', 'LICENSE', 'SHA256SUMS')
    Get-ChildItem -LiteralPath $TreeRoot -Recurse -Force -File | ForEach-Object {
        if ($textExtensions -contains $_.Extension.ToLowerInvariant() -or $textNames -contains $_.Name) {
            $text = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)
            $lf = $text.Replace("`r`n", "`n").Replace("`r", "`n")
            if ($lf -cne $text) {
                [IO.File]::WriteAllText($_.FullName, $lf, [Text.UTF8Encoding]::new($false))
            }
        }
    }
}

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

$rootFiles = @('README.md', 'pyproject.toml', '.gitignore', '.gitattributes')
foreach ($item in $rootFiles) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination $target -Force
}
foreach ($item in @('CHANGELOG.md', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md')) {
    Copy-Item -LiteralPath (Join-Path $root "agent-plugin\aicad-agent\$item") -Destination $target -Force
}
Copy-Item -LiteralPath (Join-Path $root 'agent-plugin\aicad-agent\LICENSE') -Destination $target -Force

foreach ($item in @('.github', '.agents', 'src', 'schema', 'examples', 'prompts', 'docs', 'plugin', 'agent-plugin', 'scripts', 'tests', 'tools')) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination $target -Recurse -Force
}

$assembledPlugin = [IO.Path]::GetFullPath((Join-Path $root $PluginDirectory))
if (-not $assembledPlugin.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Marketplace plugin directory must stay inside release: $assembledPlugin"
}
foreach ($required in @('.codex-plugin\plugin.json', 'integration-manifest.json', 'SHA256SUMS', 'runtime\src\aicad\engine.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $assembledPlugin $required) -PathType Leaf)) {
        throw "Assembled marketplace plugin is incomplete; missing $required"
    }
}
$assembledManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $assembledPlugin '.codex-plugin\plugin.json') | ConvertFrom-Json
if ([string]$assembledManifest.version -ne $Version) {
    throw "Assembled marketplace plugin version $($assembledManifest.version) does not match source version $Version."
}
$marketplacePlugin = Join-Path $target 'plugins\aicad-agent'
New-Item -ItemType Directory -Path $marketplacePlugin -Force | Out-Null
Get-ChildItem -LiteralPath $assembledPlugin -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $marketplacePlugin -Recurse -Force
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

Convert-TreeTextToLf -TreeRoot $target

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
    install = [ordered]@{
        marketplace = "codex plugin marketplace add JMET04/aicad-agent --ref v$Version"
        plugin = 'codex plugin add aicad-agent@aicad-agent'
    }
    capabilities = @(
        'cross-domain normative-first preflight with applicable-standard and rule-pack binding',
        'whole user-requirement contract and controlled actualBinding',
        'non-skippable whole-intent, detail-normality and hashed-build gates',
        'origin-anchored deterministic 2D AICAD compilation',
        'fail-closed production-readiness contract with authority, paper-space, furniture, route-clearance, host and release gates',
        'architectural plan-cut/projection/hidden/datum hierarchy with structure-supported axis groups, executable annotation occupancy and native dimension QA',
        'bounded independent-rank and packaging dieline normality proof',
        'aligned interactive edge/corner/face review surface',
        'typed selected line/point/circle/face measurements from compiled model geometry',
        'one synchronized MODEL_XYZ switch across 2D origins and rotating 3D axes',
        'exact source-bound subobject correction and arbitrary semantic sections',
        'optional AutoCAD and SolidWorks native hosts',
        'root-cause, correction and persistent prevention-rule audit'
    )
    safetyLocks = [ordered]@{
        reviewOnly = $true
        accepted = $false
        ruleEnabled = $false
        packagingGated = $true
        comparativeSuperiorityClaimAllowed = $false
    }
    excluded = @('jobs', 'research/paper/experiments', 'build outputs', 'native customer drawings', 'personal paths', 'credentials', 'caches', 'SolidWorks interop binaries')
    validationCommands = @(
        'python -B -m unittest discover -s tests -v',
        'python -B -m unittest discover -s agent-plugin/aicad-agent/tests -v',
        'python -B scripts/verify_release_package.py plugins/aicad-agent',
        'python -B scripts/verify_github_source.py .'
    )
    files = $entries
}
[IO.File]::WriteAllText(
    (Join-Path $target 'source-manifest.json'),
    (($manifest | ConvertTo-Json -Depth 20).Replace("`r`n", "`n").Replace("`r", "`n")) + "`n",
    [Text.UTF8Encoding]::new($false)
)

Write-Host "GitHub source staging created: $target"

