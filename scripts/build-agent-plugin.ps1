[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release',
    [string]$Version = '1.10.1',
    [switch]$IncludeSolidWorksInterop
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

Convert-TreeTextToLf -TreeRoot $stage

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
        pythonConstraintCompiler = '1.10.1'
        autocadBundle = '1.5.0'
        plan2dSchema = '2.0'
        plan3dSchema = '1.0'
        viewPackageSchema = '1.1'
    }
    releaseDate = '2026-08-12'
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
        'aicad_capabilities', 'aicad_get_plan_schema',
        'aicad_get_architecture_detail_contract_schema', 'aicad_validate_architecture_detail_contract', 'aicad_generate',
        'aicad_validate_plan', 'aicad_compile_plan',
        'aicad_get_semantic_schema', 'aicad_get_correction_schema', 'aicad_get_view_package_schema',
        'aicad_describe_plan', 'aicad_preview_correction', 'aicad_apply_correction', 'aicad_build_multiview_review',
        'aicad_get_domain_validation_schema', 'aicad_validate_domain_plan',
        'aicad_get_reference_rebuild_schema', 'aicad_validate_reference_rebuild', 'aicad_build_reference_reconstruction',
        'aicad_solidworks_doctor',
        'aicad_get_3d_plan_schema', 'aicad_validate_3d_plan', 'aicad_build_solidworks_part',
        'scripts/aicad_packaging_qa.py', 'scripts/aicad_architecture_detail_qa.py', 'scripts/aicad_architecture_qa.py', 'scripts/aicad_review_report.py', 'scripts/aicad_production_readiness_qa.py', 'scripts/aicad_production_readiness_qa_v2.py', 'scripts/aicad_report_qa.py', 'scripts/aicad_normality_prover.py', 'scripts/aicad_normality_review.py',
        'scripts/aicad_requirement_conformance.py', 'scripts/aicad_guarded_delivery.py', 'scripts/aicad_modifier_ui_qa.cjs',
        'scripts/aicad_modifier_measurement_qa.cjs'
    )
    capabilities = @(
        'origin-anchored 2D constraints', 'ASCII AICAD compilation', 'DXF/SCR/audit/manifest output',
        'architectural plan-cut/projection/hidden/datum hierarchy with complete axis groups, stage annotation matrix and native DIMSTYLE QA',
        'fail-closed production-readiness contract with paper-space, furniture component, authority, host and release gates',
        'idempotent audit-report inventory with unique stable prevention-rule IDs and conflict rejection',
        'calibrated webpage/SVG/image reference reconstruction', 'direct DOM object evidence and browser-backed annotation QA',
        'packaging dieline global QA and prevention rules', 'bounded CAD normality proof and typed top/bottom closure families',
        'whole user-requirement conformance before geometry', 'non-skippable whole-intent detail-proof and hashed candidate-build order',
        'aligned direct-selection review surface with edge/corner/face labels', 'exact edge/circle/face correction transactions with preserve policies',
        'shared-pattern fanout protection and full dependency replay', 'positive residual-wall product invariant',
        'single-flow CAD modifier with clickable core parameters', 'arbitrary semantic section planes and selectable section curves',
        'hover-discovered centers, axes, pitch circles and interface edges',
        'typed line/point/circle/face measurements in right-handed MODEL_XYZ',
        'synchronized coordinate-system visibility across SVG and rotating 3D views', 'transactional SolidWorks feature planning',
        'native SolidWorks sketch/BREP persistent-reference catalog', 'native SLDPRT save/reopen per-reference verification'
    )
    externalDependencies = @(
        [ordered]@{name='ezdxf'; requirement='>=1.4,<2'; purpose='optional packaging DXF QA'; license='MIT'},
        [ordered]@{name='jsonschema'; requirement='>=4.23,<5'; purpose='normality and requirement-contract schema validation'; license='MIT'},
        [ordered]@{name='Pillow'; requirement='>=11,<12'; purpose='optional preview QA'; license='HPND'},
        [ordered]@{name='Shapely'; requirement='>=2.1,<3'; purpose='optional topology QA'; license='BSD-3-Clause'},
        [ordered]@{name='Playwright'; requirement='optional external runtime'; purpose='real-browser reference and multiview transaction QA'; license='Apache-2.0'}
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
        'native DWG requires AutoCAD', 'native SLDPRT/STEP and native topology authority require a licensed SolidWorks installation',
        'default package excludes SolidWorks interop binaries', 'raw webpage/image pixels are never dimensional authority',
        'native AutoCAD DIMENSION/DWG output remains a host post-process', 'packaging QA remains engineering-review evidence, not manufacturing acceptance',
        'production-readiness pass creates a release candidate only; authorized professional or manufacturing acceptance remains external'
    )
    validationCommands = @(
        'PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v',
        'PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s agent-plugin/aicad-agent/tests -v',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py capabilities',
        'python agent-plugin/aicad-agent/scripts/aicad_report_qa.py <validation.json> --output <report-qa.json>',
        'python agent-plugin/aicad-agent/scripts/aicad_production_readiness_qa_v2.py <production-contract-v2.json> --output <production-validation.json> --markdown <production-validation.md> --html <production-validation.review.html> --png <production-validation.review.png>',
        'node agent-plugin/aicad-agent/scripts/aicad_reference_visual_qa.cjs --help-or-preview-arguments',
        'node agent-plugin/aicad-agent/scripts/aicad_modifier_ui_qa.cjs <review.html> <report.json> <screenshot.png>',
        'node agent-plugin/aicad-agent/scripts/aicad_modifier_measurement_qa.cjs <review.html> <report.json> <screenshot.png>'
    )
    files = $fileEntries
}
$releaseManifestJson = ($releaseManifest | ConvertTo-Json -Depth 20).Replace("`r`n", "`n").Replace("`r", "`n")
[IO.File]::WriteAllText((Join-Path $stage 'integration-manifest.json'), $releaseManifestJson + "`n", [Text.UTF8Encoding]::new($false))
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
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    (Join-Path $output 'SHA256SUMS'),
    "$archiveHash  $([IO.Path]::GetFileName($archive))`n",
    [Text.UTF8Encoding]::new($false)
)
Write-Host "Agent plugin created: $archive"
