[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release\v1.17.0\github-repository',
    [string]$Version = '1.17.0',
    [string]$PluginArchive = 'release\v1.17.0\aicad-agent-1.17.0.zip',
    [string]$PluginDirectory = 'release\v1.17.0\aicad-agent'
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

function Get-GitHubSourceInputFiles {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$AssembledPlugin,
        [Parameter(Mandatory = $true)][string]$Archive
    )
    $rows = [Collections.Generic.List[IO.FileInfo]]::new()
    $skipNames = @('__pycache__', '.pytest_cache', 'bin', 'obj')
    $skipExtensions = @('.pyc', '.pyo', '.rej', '.orig')
    function Add-Tree([string]$Tree) {
        if (-not (Test-Path -LiteralPath $Tree -PathType Container)) { return }
        Get-ChildItem -LiteralPath $Tree -Recurse -Force -File | ForEach-Object {
            $relative = $_.FullName.Substring($RepositoryRoot.Length).TrimStart('\').Replace('\', '/')
            $parts = $relative.Split('/')
            if (-not ($parts | Where-Object { $skipNames -contains $_ }) -and $skipExtensions -notcontains $_.Extension.ToLowerInvariant()) {
                $rows.Add($_)
            }
        }
    }
    foreach ($relative in @('README.md', 'pyproject.toml', '.gitignore', '.gitattributes')) {
        $rows.Add((Get-Item -LiteralPath (Join-Path $RepositoryRoot $relative)))
    }
    foreach ($relative in @('.github', '.agents', 'src', 'schema', 'examples', 'prompts', 'docs', 'plugin', 'agent-plugin', 'scripts', 'tests', 'tools', 'showcase')) {
        Add-Tree (Join-Path $RepositoryRoot $relative)
    }
    foreach ($relative in @(
        'solidworks-host\AiCad.SolidWorksHost\Program.cs',
        'solidworks-host\AiCad.SolidWorksHost\AiCad.SolidWorksHost.csproj'
    )) {
        $rows.Add((Get-Item -LiteralPath (Join-Path $RepositoryRoot $relative)))
    }
    Add-Tree $AssembledPlugin
    $rows.Add((Get-Item -LiteralPath $Archive))
    return @($rows | Sort-Object FullName -Unique)
}

function Get-SourceInputEntries {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][IO.FileInfo[]]$Files
    )
    return @($Files | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($RepositoryRoot.Length).TrimStart('\').Replace('\', '/')
            size = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        }
    })
}

$root = Split-Path -Parent $PSScriptRoot
$root = [IO.Path]::GetFullPath($root).TrimEnd('\')
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $root 'release'))
$finalTarget = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
if (-not $finalTarget.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Source output must stay inside release: $finalTarget"
}
$targetParent = Split-Path -Parent $finalTarget
New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
$targetLeaf = Split-Path -Leaf $finalTarget
$nonce = [Guid]::NewGuid().ToString('N')
$target = Join-Path $targetParent ".$targetLeaf.$nonce.staging"
$backupTarget = Join-Path $targetParent ".$targetLeaf.$nonce.backup"
New-Item -ItemType Directory -Path $target -Force | Out-Null
[IO.File]::SetAttributes($target, [IO.File]::GetAttributes($target) -bor [IO.FileAttributes]::Hidden)
$published = $false
try {

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
# Showcase artifacts are content-addressed review evidence. Copy them only after
# normalization so the publisher never mutates their already-verified bytes.
Copy-Item -LiteralPath (Join-Path $root 'showcase') -Destination $target -Recurse -Force

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
    Where-Object Extension -In @('.pyc', '.pyo', '.rej', '.orig') |
    Remove-Item -Force

$archiveName = Split-Path -Leaf $archive
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $dist $archiveName)).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    (Join-Path $dist 'SHA256SUMS'),
    "$archiveHash  $archiveName`n",
    [Text.UTF8Encoding]::new($false)
)

$rootSourceManifest = [IO.Path]::GetFullPath((Join-Path $target 'source-manifest.json'))
$files = @(Get-ChildItem -LiteralPath $target -Recurse -File | Where-Object { $_.FullName -ne $rootSourceManifest })
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
    sourceInputPolicy = 'github_source_builder_v1'
    sourceBuildInputs = [ordered]@{
        pluginDirectory = $assembledPlugin.Substring($root.Length).TrimStart('\').Replace('\', '/')
        pluginArchive = $archive.Substring($root.Length).TrimStart('\').Replace('\', '/')
    }
    sourceInputs = Get-SourceInputEntries -RepositoryRoot $root -Files (Get-GitHubSourceInputFiles -RepositoryRoot $root -AssembledPlugin $assembledPlugin -Archive $archive)
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
        'canonical mechanical and PCB evidence-contract QA with mechanical BOM/native-board reverse closure and per-PCB fabrication artifacts; concludes only evidenceContractReady and never grants readiness or authorization',
        'architectural plan-cut/projection/hidden/datum hierarchy with structure-supported axis groups, executable annotation occupancy and native dimension QA',
        'bounded independent-rank and packaging dieline normality proof',
        'aligned interactive edge/corner/face review surface',
        'typed selected line/point/circle/face measurements from compiled model geometry',
        'one synchronized MODEL_XYZ switch across 2D origins and rotating 3D axes',
        'exact source-bound subobject correction and arbitrary semantic sections',
        'controlled hash-bound failure-to-lesson loop with exact closure, disabled candidates and no automatic promotion or readiness unlock',
        'canonical cross-domain normative quality contract with explicit external-verifier boundary',
        'deterministic sanitized public showcase assembly',
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
        'python -B scripts/verify_release_package.py plugins/aicad-agent --source-root <repository-root>',
        'python -B scripts/verify_github_source.py . --source-root <repository-root>'
    )
    files = $entries
}
[IO.File]::WriteAllText(
    (Join-Path $target 'source-manifest.json'),
    (($manifest | ConvertTo-Json -Depth 20).Replace("`r`n", "`n").Replace("`r", "`n")) + "`n",
    [Text.UTF8Encoding]::new($false)
)

$sourceVerifier = Join-Path $root 'scripts\verify_github_source.py'
& python -B $sourceVerifier $target --source-root $root
if ($LASTEXITCODE -ne 0) {
    throw 'Staged GitHub source failed independent verification.'
}
[IO.File]::SetAttributes(
    $target,
    [IO.FileAttributes]([int][IO.File]::GetAttributes($target) -band (-bnot [int][IO.FileAttributes]::Hidden))
)
$hadPrevious = $false
$promoted = $false
try {
    if (Test-Path -LiteralPath $finalTarget) {
        Move-Item -LiteralPath $finalTarget -Destination $backupTarget
        $hadPrevious = $true
    }
    Move-Item -LiteralPath $target -Destination $finalTarget
    $promoted = $true
    & python -B $sourceVerifier $finalTarget --source-root $root
    if ($LASTEXITCODE -ne 0) { throw 'Published GitHub source failed post-rename verification.' }
    if ($hadPrevious -and (Test-Path -LiteralPath $backupTarget)) {
        Remove-Item -LiteralPath $backupTarget -Recurse -Force
    }
    $published = $true
} catch {
    if ($promoted -and (Test-Path -LiteralPath $finalTarget)) {
        Remove-Item -LiteralPath $finalTarget -Recurse -Force
    }
    if ($hadPrevious -and (Test-Path -LiteralPath $backupTarget)) {
        Move-Item -LiteralPath $backupTarget -Destination $finalTarget
    }
    throw
}
Write-Host "GitHub source staging created: $finalTarget"
} finally {
    if (-not $published -and (Test-Path -LiteralPath $target)) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
