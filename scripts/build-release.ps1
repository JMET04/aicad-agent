[CmdletBinding()]
param(
    [string]$OutputDirectory = 'release',
    [string]$Version = '1.10.0'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root $OutputDirectory
$version = $Version
$stage = Join-Path $output "AiCadConstraint-$version"
$archive = Join-Path $output "AiCadConstraint-$version.zip"

if (Test-Path -LiteralPath $stage) {
    $resolvedStage = (Resolve-Path -LiteralPath $stage).Path
    $resolvedOutput = (Resolve-Path -LiteralPath $output).Path
    if (-not $resolvedStage.StartsWith($resolvedOutput, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear staging path outside release directory: $resolvedStage"
    }
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}

New-Item -ItemType Directory -Path $stage -Force | Out-Null
$items = @('README.md', 'pyproject.toml', 'src', 'tools', 'plugin', 'agent-plugin', 'scripts', 'schema', 'prompts', 'docs', 'examples', 'tests')
foreach ($item in $items) {
    Copy-Item -LiteralPath (Join-Path $root $item) -Destination $stage -Recurse -Force
}

$resolvedStage = (Resolve-Path -LiteralPath $stage).Path
Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force |
    Where-Object Name -eq '__pycache__' |
    Sort-Object FullName -Descending |
    ForEach-Object {
        $candidate = (Resolve-Path -LiteralPath $_.FullName).Path
        if (-not $candidate.StartsWith($resolvedStage + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove cache directory outside release staging: $candidate"
        }
        Remove-Item -LiteralPath $candidate -Recurse -Force
    }
Get-ChildItem -LiteralPath $stage -Filter '*.pyc' -File -Recurse -Force | Remove-Item -Force

if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($archive, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in Get-ChildItem -LiteralPath $stage -Recurse -File) {
        $relative = $file.FullName.Substring($output.Length).TrimStart('\').Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip,
            $file.FullName,
            $relative,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
} finally {
    $zip.Dispose()
}
Write-Host "Release created: $archive"
