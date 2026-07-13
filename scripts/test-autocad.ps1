[CmdletBinding()]
param(
    [string]$InstallDirectory,
    [string]$PythonExe = 'python',
    [string]$TestRoot = (Join-Path $env:TEMP 'AiCadConstraintHostTest')
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not $InstallDirectory) {
    $installKey = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Autodesk\AutoCAD\R25.0\ACAD-8101\Install' -ErrorAction SilentlyContinue
    $InstallDirectory = $installKey.INSTALLDIR
}
if (-not $InstallDirectory) {
    throw 'AutoCAD install directory was not found. Pass -InstallDirectory explicitly.'
}

$coreConsole = Join-Path $InstallDirectory 'accoreconsole.exe'
if (-not (Test-Path -LiteralPath $coreConsole -PathType Leaf)) {
    throw "AutoCAD Core Console was not found: $coreConsole"
}

$pythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
if (-not $pythonCommand -and -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python executable was not found: $PythonExe"
}

$outputDirectory = Join-Path $root 'build\autocad-host-test'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
& $PythonExe (Join-Path $root 'tools\aicad.py') compile (Join-Path $root 'examples\rectangle.plan.json') --out $outputDirectory --name rectangle
if ($LASTEXITCODE -ne 0) {
    throw 'The example plan failed to compile.'
}
& $PythonExe (Join-Path $root 'tools\aicad.py') compile (Join-Path $root 'examples\arc.plan.json') --out $outputDirectory --name arc
if ($LASTEXITCODE -ne 0) {
    throw 'The arc plan failed to compile.'
}
& $PythonExe (Join-Path $root 'agent-plugin\aicad-agent\scripts\aicad_agent.py') generate --request '120x80 plate with centered diameter 20 hole' --out $outputDirectory --name agent-plate --provider offline
if ($LASTEXITCODE -ne 0) {
    throw 'The agent plugin failed to generate its AutoCAD test artifact.'
}

New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null
$testRootResolved = (Resolve-Path -LiteralPath $TestRoot).Path
$testFiles = @(
    'result.dwg',
    'integration-report.txt',
    'persistence-report.txt',
    'v2-report.txt',
    'agent-plugin-report.txt',
    'integration.stdout.bin',
    'integration.stderr.bin',
    'persistence.stdout.bin',
    'persistence.stderr.bin',
    'v2.stdout.bin',
    'v2.stderr.bin',
    'agent-plugin.stdout.bin',
    'agent-plugin.stderr.bin'
)
foreach ($name in $testFiles) {
    $path = Join-Path $testRootResolved $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        if (-not $resolved.StartsWith($testRootResolved + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a test file outside the test root: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Force
    }
}

$copies = @{
    (Join-Path $root 'plugin\AiCadConstraint.bundle\Contents\AiCadConstraint.lsp') = 'AiCadConstraint.lsp'
    (Join-Path $root 'tests\autocad\integration_test.lsp') = 'integration_test.lsp'
    (Join-Path $root 'tests\autocad\run-integration.scr') = 'run-integration.scr'
    (Join-Path $root 'tests\autocad\run-persistence.scr') = 'run-persistence.scr'
    (Join-Path $root 'tests\autocad\v2_test.lsp') = 'v2_test.lsp'
    (Join-Path $root 'tests\autocad\run-v2.scr') = 'run-v2.scr'
    (Join-Path $root 'tests\autocad\agent_plugin_test.lsp') = 'agent_plugin_test.lsp'
    (Join-Path $root 'tests\autocad\run-agent-plugin.scr') = 'run-agent-plugin.scr'
    (Join-Path $outputDirectory 'rectangle.aicad') = 'rectangle.aicad'
    (Join-Path $outputDirectory 'rectangle.dxf') = 'input.dxf'
    (Join-Path $outputDirectory 'arc.aicad') = 'arc.aicad'
    (Join-Path $outputDirectory 'agent-plate.aicad') = 'agent-plate.aicad'
}
foreach ($source in $copies.Keys) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $testRootResolved $copies[$source]) -Force
}

function Invoke-AutoCadCoreTest {
    param(
        [Parameter(Mandatory)] [string]$InputDrawing,
        [Parameter(Mandatory)] [string]$Script,
        [Parameter(Mandatory)] [string]$LogPrefix
    )
    $stdout = Join-Path $testRootResolved "$LogPrefix.stdout.bin"
    $stderr = Join-Path $testRootResolved "$LogPrefix.stderr.bin"
    $arguments = '/i "{0}" /s "{1}" /l zh-CN' -f $InputDrawing, $Script
    $process = Start-Process -FilePath $coreConsole -ArgumentList $arguments -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "AutoCAD Core Console timed out: $LogPrefix (PID $($process.Id))"
    }
    $process.WaitForExit()
}

$oldEnvironment = @{}
foreach ($name in @('AICAD_TEST_ROOT', 'AICAD_PYTHON', 'AICAD_PYTHONW', 'AICAD_RUNNER', 'AICAD_JOBS')) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:AICAD_TEST_ROOT = $testRootResolved
    $env:AICAD_PYTHON = (Resolve-Path -LiteralPath $PythonExe).Path
    $env:AICAD_PYTHONW = $env:AICAD_PYTHON
    $env:AICAD_RUNNER = Join-Path $root 'tools\aicad.py'
    $env:AICAD_JOBS = $testRootResolved
    Invoke-AutoCadCoreTest -InputDrawing (Join-Path $testRootResolved 'input.dxf') -Script (Join-Path $testRootResolved 'run-integration.scr') -LogPrefix 'integration'
    $integration = Get-Content -LiteralPath (Join-Path $testRootResolved 'integration-report.txt')
    if ($integration -notcontains 'AICAD_INTEGRATION_PASS') {
        throw "AutoCAD integration failed: $($integration -join '; ')"
    }

    Invoke-AutoCadCoreTest -InputDrawing (Join-Path $testRootResolved 'result.dwg') -Script (Join-Path $testRootResolved 'run-persistence.scr') -LogPrefix 'persistence'
    $persistence = Get-Content -LiteralPath (Join-Path $testRootResolved 'persistence-report.txt')
    if ($persistence -notcontains 'AICAD_PERSISTENCE_PASS') {
        throw "AutoCAD persistence check failed: $($persistence -join '; ')"
    }
    Invoke-AutoCadCoreTest -InputDrawing (Join-Path $testRootResolved 'input.dxf') -Script (Join-Path $testRootResolved 'run-v2.scr') -LogPrefix 'v2'
    $v2 = Get-Content -LiteralPath (Join-Path $testRootResolved 'v2-report.txt')
    if ($v2 -notcontains 'AICAD_V2_PASS') {
        throw "AutoCAD protocol v2 check failed: $($v2 -join '; ')"
    }
    Invoke-AutoCadCoreTest -InputDrawing (Join-Path $testRootResolved 'input.dxf') -Script (Join-Path $testRootResolved 'run-agent-plugin.scr') -LogPrefix 'agent-plugin'
    $agentPlugin = Get-Content -LiteralPath (Join-Path $testRootResolved 'agent-plugin-report.txt')
    if ($agentPlugin -notcontains 'AICAD_AGENT_PASS') {
        throw "Agent-plugin AutoCAD check failed: $($agentPlugin -join '; ')"
    }
} finally {
    foreach ($name in $oldEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], 'Process')
    }
}

Copy-Item -LiteralPath (Join-Path $testRootResolved 'result.dwg') -Destination (Join-Path $outputDirectory 'result.dwg') -Force
Copy-Item -LiteralPath (Join-Path $testRootResolved 'integration-report.txt') -Destination (Join-Path $outputDirectory 'integration-report.txt') -Force
Copy-Item -LiteralPath (Join-Path $testRootResolved 'persistence-report.txt') -Destination (Join-Path $outputDirectory 'persistence-report.txt') -Force
Copy-Item -LiteralPath (Join-Path $testRootResolved 'v2-report.txt') -Destination (Join-Path $outputDirectory 'v2-report.txt') -Force
Copy-Item -LiteralPath (Join-Path $testRootResolved 'agent-plugin-report.txt') -Destination (Join-Path $outputDirectory 'agent-plugin-report.txt') -Force

$dwg = Get-Item -LiteralPath (Join-Path $outputDirectory 'result.dwg')
$signature = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($dwg.FullName), 0, 6)
$summary = [pscustomobject]@{
    Status = 'PASS'
    AutoCADCoreConsole = $coreConsole
    AutoCADFileVersion = (Get-Item -LiteralPath $coreConsole).VersionInfo.FileVersion
    DrawingSignature = $signature
    DrawingBytes = $dwg.Length
    IntegrationReport = (Join-Path $outputDirectory 'integration-report.txt')
    PersistenceReport = (Join-Path $outputDirectory 'persistence-report.txt')
    ProtocolV2Report = (Join-Path $outputDirectory 'v2-report.txt')
    AgentPluginReport = (Join-Path $outputDirectory 'agent-plugin-report.txt')
    ResultDrawing = $dwg.FullName
}
$summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDirectory 'host-validation.json') -Encoding UTF8
$summary | Format-List
