[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release',
    [string]$Version = '1.3.2',
    [switch]$IncludeSolidWorksInterop
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
$template = Join-Path $root 'agent-plugin\aicad-agent'
$stage = Join-Path $output 'aicad-agent'
$archive = Join-Path $output "aicad-agent-$Version.zip"

if (-not (Test-Path -LiteralPath $template -PathType Container)) {
    throw "Agent plugin template is missing: $template"
}
New-Item -ItemType Directory -Path $output -Force | Out-Null
if (Test-Path -LiteralPath $stage) {
    $resolved = (Resolve-Path -LiteralPath $stage).Path
    if (-not $resolved.StartsWith($output + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear agent-plugin staging outside release: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

New-Item -ItemType Directory -Path $stage -Force | Out-Null
Get-ChildItem -LiteralPath $template -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $stage -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $root 'scripts\verify_release_package.py') -Destination (Join-Path $stage 'scripts') -Force

$runtime = Join-Path $stage 'runtime'
New-Item -ItemType Directory -Path (Join-Path $runtime 'src'), (Join-Path $runtime 'schema'), (Join-Path $runtime 'examples') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'src\aicad') -Destination (Join-Path $runtime 'src') -Recurse -Force
Get-ChildItem -LiteralPath (Join-Path $root 'schema') -File -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $runtime 'schema') -Force
}
Get-ChildItem -LiteralPath (Join-Path $root 'examples') -File -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $runtime 'examples') -Force
}
$solidWorksHostSource = Join-Path $root 'solidworks-host\AiCad.SolidWorksHost'
$solidWorksSourceStage = Join-Path $runtime 'solidworks-host-source'
New-Item -ItemType Directory -Path $solidWorksSourceStage -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $solidWorksHostSource 'Program.cs') -Destination $solidWorksSourceStage -Force
Copy-Item -LiteralPath (Join-Path $solidWorksHostSource 'AiCad.SolidWorksHost.csproj') -Destination $solidWorksSourceStage -Force
Copy-Item -LiteralPath (Join-Path $root 'scripts\build-solidworks-host.ps1') -Destination $solidWorksSourceStage -Force
if ($IncludeSolidWorksInterop) {
    $solidWorksHost = Join-Path $root 'build\solidworks-host'
    if (-not (Test-Path -LiteralPath (Join-Path $solidWorksHost 'AiCad.SolidWorksHost.exe') -PathType Leaf)) {
        & (Join-Path $PSScriptRoot 'build-solidworks-host.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'SolidWorks host build failed.' }
    }
    Copy-Item -LiteralPath $solidWorksHost -Destination (Join-Path $runtime 'solidworks-host') -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $root 'plugin\AiCadConstraint.bundle') -Destination (Join-Path $runtime 'autocad') -Recurse -Force

$resolvedStage = (Resolve-Path -LiteralPath $stage).Path
Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force |
    Where-Object Name -eq '__pycache__' |
    Sort-Object FullName -Descending |
    ForEach-Object {
        $candidate = (Resolve-Path -LiteralPath $_.FullName).Path
        if (-not $candidate.StartsWith($resolvedStage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove cache outside plugin staging: $candidate"
        }
        Remove-Item -LiteralPath $candidate -Recurse -Force
    }
Get-ChildItem -LiteralPath $stage -Filter '*.pyc' -File -Recurse -Force | Remove-Item -Force

$pluginManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $stage '.codex-plugin\plugin.json') | ConvertFrom-Json
if ([string]$pluginManifest.version -ne $Version) {
    throw "Plugin version $($pluginManifest.version) does not match build version $Version."
}
$payloadFiles = @(Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object Name -NotIn @('integration-manifest.json', 'SHA256SUMS'))
$fileEntries = @($payloadFiles | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($resolvedStage.Length).TrimStart('\').Replace('\', '/')
        size = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    }
})
$releaseManifest = [ordered]@{
    schema = 'aicad_agent_release_manifest_v1'
    name = 'aicad-agent'
    version = $Version
    componentVersions = [ordered]@{
        agentPlugin = $Version
        pythonConstraintCompiler = '1.3.2'
        autocadBundle = '1.3.2'
        plan2dSchema = '2.0'
        plan3dSchema = '1.0'
    }
    releaseDate = '2026-08-10'
    license = 'MIT'
    repository = 'https://github.com/JMET04/aicad-agent'
    apiKeyRequired = $false
    defaultInvocation = 'current Agent authors caller plan; local validator/compiler executes without provider API'
    runtimes = [ordered]@{
        python = '>=3.10'
        codex = 'plugin manifest plus stdio MCP'
        autocad = 'optional; source bundle included; AutoCAD 2025 evidence exists'
        solidworks = 'optional; source/build helper included; SolidWorks 2026 evidence exists'
    }
    tools = @(
        'aicad_capabilities', 'aicad_get_plan_schema', 'aicad_generate',
        'aicad_validate_plan', 'aicad_compile_plan', 'aicad_solidworks_doctor',
        'aicad_get_3d_plan_schema', 'aicad_validate_3d_plan', 'aicad_build_solidworks_part',
        'scripts/aicad_packaging_qa.py', 'scripts/aicad_normality_prover.py', 'scripts/aicad_normality_review.py',
        'scripts/aicad_requirement_conformance.py', 'scripts/aicad_guarded_delivery.py'
    )
    capabilities = @(
        'origin-anchored 2D constraints', 'ASCII AICAD compilation', 'DXF/SCR/audit/manifest output',
        'packaging dieline global QA and prevention rules', 'bounded CAD normality proof and typed top/bottom closure families',
        'whole user-requirement conformance before geometry', 'non-skippable whole-intent detail-proof and hashed candidate-build order',
        'aligned direct-selection review surface with edge/corner/face labels', 'transactional SolidWorks feature planning',
        'optional native host save/reopen verification'
    )
    externalDependencies = @(
        [ordered]@{name='ezdxf'; requirement='>=1.4,<2'; purpose='optional packaging DXF QA'; license='MIT'},
        [ordered]@{name='Pillow'; requirement='>=11,<12'; purpose='optional preview QA'; license='HPND'},
        [ordered]@{name='Shapely'; requirement='>=2.1,<3'; purpose='optional topology QA'; license='BSD-3-Clause'}
    )
    proprietaryDependenciesRedistributed = $false
    safetyLocks = [ordered]@{
        reviewOnly = $true
        accepted = $false
        ruleEnabled = $false
        packagingGated = $true
        comparativeSuperiorityClaimAllowed = $false
    }
    knownLimitations = @(
        'native DWG requires AutoCAD', 'native SLDPRT/STEP host execution requires a licensed SolidWorks installation',
        'default package excludes SolidWorks interop binaries', 'packaging QA remains engineering-review evidence, not manufacturing acceptance'
    )
    validationCommands = @(
        'python -m unittest discover -s tests -v',
        'python -m unittest discover -s agent-plugin/aicad-agent/tests -v',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py capabilities'
    )
    files = $fileEntries
}
$releaseManifestJson = $releaseManifest | ConvertTo-Json -Depth 20
[IO.File]::WriteAllText((Join-Path $stage 'integration-manifest.json'), $releaseManifestJson + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
$sumFiles = @(Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object Name -ne 'SHA256SUMS')
$sumLines = @($sumFiles | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($resolvedStage.Length).TrimStart('\').Replace('\', '/')
    "$( (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant() )  $relative"
})
[IO.File]::WriteAllText((Join-Path $stage 'SHA256SUMS'), ($sumLines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in Get-ChildItem -LiteralPath $stage -Recurse -File) {
        $relative = $file.FullName.Substring($output.Length).TrimStart('\').Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $relative, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $zip.Dispose()
}
Write-Host "Agent plugin created: $archive"
