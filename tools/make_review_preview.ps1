param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Bitmap]::FromFile((Resolve-Path -LiteralPath $InputPath))
try {
    $targetWidth = 720
    $targetHeight = [Math]::Max(1, [int][Math]::Round($source.Height * $targetWidth / $source.Width))
    $target = New-Object System.Drawing.Bitmap($targetWidth, $targetHeight)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($target)
        try {
            $graphics.Clear([System.Drawing.Color]::White)
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.DrawImage($source, 0, 0, $targetWidth, $targetHeight)
        }
        finally { $graphics.Dispose() }
        $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq 'image/jpeg'
        $parameters = New-Object System.Drawing.Imaging.EncoderParameters(1)
        $parameters.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]42)
        $target.Save($OutputPath, $codec, $parameters)
        $parameters.Dispose()
    }
    finally { $target.Dispose() }
}
finally { $source.Dispose() }

Get-Item -LiteralPath $OutputPath | Select-Object FullName,Length
