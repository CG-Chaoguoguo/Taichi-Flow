[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$assetRoot = Join-Path $repositoryRoot "frontend\taichi-flow\desktop\assets"
$pngPath = Join-Path $assetRoot "taichi-flow-dev.png"
$icoPath = Join-Path $assetRoot "taichi-flow-dev.ico"
$sizes = @(16, 24, 32, 48, 64, 128, 256)

function New-BrandBitmap {
    param([Parameter(Mandatory = $true)][int]$Size)
    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $radius = [Math]::Max(2, [Math]::Round($Size * 0.21))
        $diameter = $radius * 2
        $path = New-Object System.Drawing.Drawing2D.GraphicsPath
        try {
            $path.AddArc(0, 0, $diameter, $diameter, 180, 90)
            $path.AddArc($Size - $diameter - 1, 0, $diameter, $diameter, 270, 90)
            $path.AddArc($Size - $diameter - 1, $Size - $diameter - 1, $diameter, $diameter, 0, 90)
            $path.AddArc(0, $Size - $diameter - 1, $diameter, $diameter, 90, 90)
            $path.CloseFigure()
            $brandBrush = New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml("#7170ff"))
            try { $graphics.FillPath($brandBrush, $path) } finally { $brandBrush.Dispose() }
        } finally {
            $path.Dispose()
        }

        $fontSize = [Math]::Max(6, $Size * 0.345)
        $font = New-Object System.Drawing.Font("Segoe UI", $fontSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $format = New-Object System.Drawing.StringFormat
        try {
            $format.Alignment = [System.Drawing.StringAlignment]::Center
            $format.LineAlignment = [System.Drawing.StringAlignment]::Center
            $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
            $rectangle = New-Object System.Drawing.RectangleF(0, -($Size * 0.01), $Size, $Size)
            $graphics.DrawString("TF", $font, $whiteBrush, $rectangle, $format)
        } finally {
            $format.Dispose()
            $whiteBrush.Dispose()
            $font.Dispose()
        }
    } finally {
        $graphics.Dispose()
    }
    return $bitmap
}

New-Item -ItemType Directory -Path $assetRoot -Force | Out-Null
$master = New-BrandBitmap -Size 256
try { $master.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png) } finally { $master.Dispose() }

$images = New-Object System.Collections.Generic.List[byte[]]
foreach ($size in $sizes) {
    $bitmap = New-BrandBitmap -Size $size
    $stream = New-Object System.IO.MemoryStream
    try {
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $images.Add($stream.ToArray())
    } finally {
        $stream.Dispose()
        $bitmap.Dispose()
    }
}

$fileStream = [System.IO.File]::Open($icoPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$writer = New-Object System.IO.BinaryWriter($fileStream)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$sizes.Count)
    $offset = 6 + (16 * $sizes.Count)
    for ($index = 0; $index -lt $sizes.Count; $index += 1) {
        $size = $sizes[$index]
        $encodedSize = if ($size -eq 256) { 0 } else { $size }
        $writer.Write([byte]$encodedSize)
        $writer.Write([byte]$encodedSize)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$images[$index].Length)
        $writer.Write([uint32]$offset)
        $offset += $images[$index].Length
    }
    foreach ($image in $images) { $writer.Write($image) }
} finally {
    $writer.Dispose()
    $fileStream.Dispose()
}

Write-Output "Generated $pngPath"
Write-Output "Generated $icoPath with $($sizes.Count) sizes"
