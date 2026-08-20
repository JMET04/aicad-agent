[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release',
    [string]$Version = '1.16.0',
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

function Get-CanonicalSourceInputFiles {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][bool]$IncludeInterop
    )
    $rows = [Collections.Generic.List[IO.FileInfo]]::new()
    $skipNames = @('__pycache__', '.pytest_cache')
    $skipExtensions = @('.pyc', '.pyo', '.rej', '.orig')
    function Add-Tree([string]$RelativePath) {
        $tree = Join-Path $RepositoryRoot $RelativePath
        if (-not (Test-Path -LiteralPath $tree -PathType Container)) { return }
        Get-ChildItem -LiteralPath $tree -Recurse -Force -File | ForEach-Object {
            $relative = $_.FullName.Substring($RepositoryRoot.Length).TrimStart('\').Replace('\', '/')
            $parts = $relative.Split('/')
            if (-not ($parts | Where-Object { $skipNames -contains $_ }) -and $skipExtensions -notcontains $_.Extension.ToLowerInvariant()) {
                $rows.Add($_)
            }
        }
    }
    Add-Tree 'agent-plugin\aicad-agent'
    Add-Tree 'src\aicad'
    Add-Tree 'plugin\AiCadConstraint.bundle'
    foreach ($relative in @('schema', 'examples')) {
        $directory = Join-Path $RepositoryRoot $relative
        if (Test-Path -LiteralPath $directory -PathType Container) {
            Get-ChildItem -LiteralPath $directory -Force -File | ForEach-Object { $rows.Add($_) }
        }
    }
    foreach ($relative in @(
        'scripts\build-agent-plugin.ps1',
        'scripts\verify_release_package.py',
        'solidworks-host\AiCad.SolidWorksHost\Program.cs',
        'solidworks-host\AiCad.SolidWorksHost\AiCad.SolidWorksHost.csproj',
        'scripts\build-solidworks-host.ps1'
    )) {
        $path = Join-Path $RepositoryRoot $relative
        if (Test-Path -LiteralPath $path -PathType Leaf) { $rows.Add((Get-Item -LiteralPath $path)) }
    }
    if ($IncludeInterop) { Add-Tree 'build\solidworks-host' }
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
$finalOutput = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
if (-not $finalOutput.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Agent-plugin output must stay inside release: $finalOutput"
}
$outputParent = Split-Path -Parent $finalOutput
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$leaf = Split-Path -Leaf $finalOutput
$nonce = [Guid]::NewGuid().ToString('N')
$output = Join-Path $outputParent ".$leaf.$nonce.staging"
$backupOutput = Join-Path $outputParent ".$leaf.$nonce.backup"
New-Item -ItemType Directory -Path $output -Force | Out-Null
[IO.File]::SetAttributes($output, [IO.File]::GetAttributes($output) -bor [IO.FileAttributes]::Hidden)
$template = Join-Path $root 'agent-plugin\aicad-agent'
$stage = Join-Path $output 'aicad-agent'
$archive = Join-Path $output "aicad-agent-$Version.zip"
$published = $false

try {
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
Get-ChildItem -LiteralPath $stage -File -Recurse -Force | Where-Object Extension -In @('.pyc', '.pyo', '.rej', '.orig') | Remove-Item -Force

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
        pythonConstraintCompiler = '1.16.0'
        autocadBundle = '1.6.0'
        plan2dSchema = '2.0'
        plan3dSchema = '1.0'
        viewPackageSchema = '1.1'
    }
    releaseDate = '2026-08-20'
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
    sourceInputPolicy = 'agent_plugin_builder_v1'
    buildOptions = [ordered]@{
        includeSolidWorksInterop = [bool]$IncludeSolidWorksInterop
    }
    sourceInputs = Get-SourceInputEntries -RepositoryRoot $root -Files (Get-CanonicalSourceInputFiles -RepositoryRoot $root -IncludeInterop ([bool]$IncludeSolidWorksInterop))
    tools = @(
        'aicad_capabilities', 'aicad_get_plan_schema',
        'aicad_get_engineering_preflight_schema', 'aicad_get_engineering_preflight_template', 'aicad_validate_engineering_preflight',
        'aicad_get_architecture_detail_contract_schema', 'aicad_validate_architecture_detail_contract', 'aicad_generate',
        'aicad_validate_plan', 'aicad_compile_plan',
        'aicad_get_semantic_schema', 'aicad_get_correction_schema', 'aicad_get_view_package_schema', 'aicad_get_review_handoff_schema',
        'aicad_describe_plan', 'aicad_preview_correction', 'aicad_apply_correction',
        'aicad_validate_review_handoff', 'aicad_apply_review_handoff',
        'aicad_build_multiview_review', 'aicad_open_review_request',
        'aicad_get_domain_validation_schema', 'aicad_validate_domain_plan',
        'aicad_get_reference_rebuild_schema', 'aicad_validate_reference_rebuild', 'aicad_build_reference_reconstruction',
        'aicad_solidworks_doctor',
        'aicad_get_3d_plan_schema', 'aicad_validate_3d_plan', 'aicad_build_solidworks_part',
        'scripts/aicad_engineering_preflight.py',
        'scripts/aicad_packaging_qa.py', 'scripts/aicad_architecture_detail_qa.py', 'scripts/aicad_architecture_qa.py', 'scripts/aicad_review_report.py', 'scripts/aicad_production_readiness_qa.py', 'scripts/aicad_production_readiness_qa_v2.py', 'scripts/aicad_production_readiness_qa_v3.py', 'scripts/aicad_report_qa.py', 'scripts/aicad_lesson_harvester.py', 'scripts/aicad_continuous_learning_qa.py', 'scripts/aicad_normality_prover.py', 'scripts/aicad_normality_review.py',
        'scripts/aicad_requirement_conformance.py', 'scripts/aicad_guarded_delivery.py', 'scripts/aicad_modifier_ui_qa.cjs',
        'scripts/aicad_modifier_measurement_qa.cjs', 'scripts/aicad_architecture_document_set_qa.py',
        'scripts/aicad_normative_quality_qa.py'
    )
    capabilities = @(
        'origin-anchored 2D constraints', 'ASCII AICAD compilation', 'DXF/SCR/audit/manifest output',
        'cross-domain normative-first preflight with declared standards, domain rule packs and non-compensatory authority order',
        'architectural plan-cut/projection/hidden/datum hierarchy with structure-supported axis groups, stage annotation matrix and native DIMSTYLE QA',
        'executable annotation occupancy QA against axes, columns, bubbles, equipment, furniture, dimensions, door leaves and swing arcs',
        'exact architecture-to-structure XY support-pair transfer without Cartesian coordinate expansion',
        'dual-viewport forward annotation reservation, semantic-distance candidate cycling and document-set isolation contracts',
        'protocol-4 native overall/grid/partition/opening DIMENSION entities with purpose XData and AutoCAD save/reopen proof',
        'persistent content-addressed review launch with duplicate auto-tab suppression',
        'direct-production requests fail closed to blocker-only output on any missing gate',
        'canonical pre-geometry mechanical/electronics normative preflight with exact 54/63 rule inventories and compile-time blocking',
        'fail-closed architecture v2 compatibility contract with paper-space, furniture component, authority, host and release gates',
        'canonical v3 evidence-contract verifier with exact multi-artifact closure, mechanical BOM subject rows, per-PCB BOM/CPL/assembly/fabrication/PDF/3D/CAM closure, native-board drill authority, repeated kinds, per-subject source/reopen binding and a full-identity digest; concludes only evidenceContractReady and never exposes candidate artifacts or grants readiness/authorization',
        'idempotent audit-report inventory with unique stable prevention-rule IDs and conflict rejection',
        'controlled deterministic failure-to-lesson harvesting with exact hash closure, disabled candidates, conflict rejection and recorded-precondition-only promotion QA that never authenticates reviewers or grants eligibility',
        'calibrated webpage/SVG/image reference reconstruction', 'direct DOM object evidence and browser-backed annotation QA',
        'packaging dieline global QA and prevention rules', 'bounded CAD normality proof and typed top/bottom closure families',
        'whole user-requirement conformance before geometry', 'non-skippable whole-intent detail-proof and hashed candidate-build order',
        'aligned direct-selection review surface with edge/corner/face labels', 'exact edge/circle/face correction transactions with preserve policies',
        'shared-pattern fanout protection and full dependency replay', 'positive residual-wall product invariant',
        'single-flow CAD modifier with clickable core parameters', 'source-hash-gated reviewer handoff validation and corrected-modifier regeneration',
        'arbitrary semantic section planes and selectable section curves',
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
        'protocol-4 native DIMENSION is emitted in DXF/AICAD; native DWG still requires licensed AutoCAD save/reopen validation', 'packaging QA remains engineering-review evidence, not manufacturing acceptance',
        'v3 evidence-contract pass produces a review report only; technical readiness, release eligibility and manufacturing/fabrication authorization remain external and false',
        'continuous-learning tools never authenticate approvers, grant promotion eligibility, mutate authoritative rules/tests or installed plugins, or unlock readiness/authorization'
    )
    validationCommands = @(
        'PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v',
        'PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s agent-plugin/aicad-agent/tests -v',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py capabilities',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py review-handoff-schema',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py validate-review-handoff --plan <plan.json> --handoff <review-handoff.json> --domain <domain>',
        'python agent-plugin/aicad-agent/scripts/aicad_agent.py apply-review-handoff --plan <plan.json> --handoff <review-handoff.json> --out <corrected-review-directory> --domain <domain>',
        'python agent-plugin/aicad-agent/scripts/aicad_engineering_preflight.py --contract <engineering-preflight.json> --output <engineering-preflight-report.json>',
        'python agent-plugin/aicad-agent/scripts/aicad_report_qa.py <validation.json> --output <report-qa.json>',
        'python agent-plugin/aicad-agent/scripts/aicad_production_readiness_qa_v2.py <production-contract-v2.json> --output <production-validation.json> --markdown <production-validation.md> --html <production-validation.review.html> --png <production-validation.review.png>',
        'python agent-plugin/aicad-agent/scripts/aicad_production_readiness_qa_v3.py <production-contract-v3.json> --output <production-validation-v3.json> --markdown <production-validation-v3.md>',
        'python agent-plugin/aicad-agent/scripts/aicad_lesson_harvester.py <failure-report.json> --root <evidence-root> --output learning/<lesson-bundle.json>',
        'python agent-plugin/aicad-agent/scripts/aicad_continuous_learning_qa.py learning/<lesson-bundle.json> --root <evidence-root> --output learning/<learning-audit.json>',
        'node agent-plugin/aicad-agent/scripts/aicad_reference_visual_qa.cjs --help-or-preview-arguments',
        'node agent-plugin/aicad-agent/scripts/aicad_modifier_ui_qa.cjs <review.html> <report.json> <screenshot.png>',
        'node agent-plugin/aicad-agent/scripts/aicad_modifier_measurement_qa.cjs <review.html> <report.json> <screenshot.png>',
        'python agent-plugin/aicad-agent/scripts/aicad_normative_quality_qa.py <normative-contract.json> --output <normative-validation.json>'
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
$releaseVerifier = Join-Path $root 'scripts\verify_release_package.py'
& python -B $releaseVerifier $stage --source-root $root --expected-version $Version
if ($LASTEXITCODE -ne 0) {
    throw 'Staged agent plugin failed independent release verification.'
}
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
[IO.File]::SetAttributes(
    $output,
    [IO.FileAttributes]([int][IO.File]::GetAttributes($output) -band (-bnot [int][IO.FileAttributes]::Hidden))
)
$hadPrevious = $false
$promoted = $false
try {
    if (Test-Path -LiteralPath $finalOutput) {
        Move-Item -LiteralPath $finalOutput -Destination $backupOutput
        $hadPrevious = $true
    }
    Move-Item -LiteralPath $output -Destination $finalOutput
    $promoted = $true
    & python -B $releaseVerifier (Join-Path $finalOutput 'aicad-agent') --source-root $root
    if ($LASTEXITCODE -ne 0) { throw 'Published agent plugin failed post-rename verification.' }
    if ($hadPrevious -and (Test-Path -LiteralPath $backupOutput)) {
        Remove-Item -LiteralPath $backupOutput -Recurse -Force
    }
    $published = $true
} catch {
    if ($promoted -and (Test-Path -LiteralPath $finalOutput)) {
        Remove-Item -LiteralPath $finalOutput -Recurse -Force
    }
    if ($hadPrevious -and (Test-Path -LiteralPath $backupOutput)) {
        Move-Item -LiteralPath $backupOutput -Destination $finalOutput
    }
    throw
}
Write-Host "Agent plugin created: $(Join-Path $finalOutput "aicad-agent-$Version.zip")"
} finally {
    if (-not $published -and (Test-Path -LiteralPath $output)) {
        Remove-Item -LiteralPath $output -Recurse -Force
    }
}
