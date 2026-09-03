param(
    [switch]$Install,
    [string]$SandboxRoot = "",
    [string]$MsysRoot = "C:\msys64"
)

$ErrorActionPreference = "Continue"

if (-not $SandboxRoot) {
    $SandboxRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$LogsDir = Join-Path $SandboxRoot "logs"
$ToolchainDir = Join-Path $SandboxRoot "toolchain"
New-Item -ItemType Directory -Force -Path $LogsDir, $ToolchainDir | Out-Null

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch {
    }
}

$commands = @()
function Invoke-LoggedCommand {
    param(
        [string]$Command,
        [string[]]$Arguments
    )
    $record = [ordered]@{
        command = $Command
        arguments = $Arguments
        exit_code = $null
        output = @()
    }
    try {
        $output = & $Command @Arguments 2>&1
        $record.exit_code = $LASTEXITCODE
        $lines = @($output | ForEach-Object { $_.ToString() })
        if ($lines.Count -gt 200) {
            $lines = @($lines[0..99] + "... truncated ..." + $lines[($lines.Count - 100)..($lines.Count - 1)])
        }
        $record.output = $lines
    } catch {
        $record.exit_code = -1
        $record.output = @($_.Exception.Message)
    }
    $script:commands += $record
    return $record
}

function Find-GFortran {
    $candidates = @(
        (Join-Path $MsysRoot "mingw64\bin\gfortran.exe"),
        (Join-Path $MsysRoot "ucrt64\bin\gfortran.exe"),
        "C:\msys64\mingw64\bin\gfortran.exe",
        "C:\msys64\ucrt64\bin\gfortran.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $cmd = Get-Command gfortran -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Record-GFortranToolVersions {
    param([string]$GFortranPath)
    if (-not $GFortranPath) {
        return
    }
    $binDir = Split-Path $GFortranPath -Parent
    if ($env:PATH -notlike "*$binDir*") {
        $env:PATH = "$binDir;$env:PATH"
    }
    Invoke-LoggedCommand -Command $GFortranPath -Arguments @("--version") | Out-Null
    Invoke-LoggedCommand -Command "where.exe" -Arguments @("gfortran") | Out-Null
    Invoke-LoggedCommand -Command "where.exe" -Arguments @("mingw32-make") | Out-Null
    Invoke-LoggedCommand -Command "where.exe" -Arguments @("make") | Out-Null
}

function Set-Msys2MirrorPreference {
    param([string]$Root)
    $pacmanDir = Join-Path $Root "etc\pacman.d"
    if (-not (Test-Path $pacmanDir)) {
        return
    }
    $mingwMirror = Join-Path $pacmanDir "mirrorlist.mingw"
    $msysMirror = Join-Path $pacmanDir "mirrorlist.msys"
    if (Test-Path $mingwMirror) {
        @(
            "# Sandbox-preferred mirrors for transient toolchain install",
            "Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/mingw/`$repo/",
            "Server = https://mirrors.bfsu.edu.cn/msys2/mingw/`$repo/",
            "Server = https://mirrors.ustc.edu.cn/msys2/mingw/`$repo/",
            "Server = https://mirrors.aliyun.com/msys2/mingw/`$repo/",
            "Server = https://repo.msys2.org/mingw/`$repo/"
        ) | Set-Content -Path $mingwMirror -Encoding ASCII
    }
    if (Test-Path $msysMirror) {
        @(
            "# Sandbox-preferred mirrors for transient toolchain install",
            "Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/msys/`$arch/",
            "Server = https://mirrors.bfsu.edu.cn/msys2/msys/`$arch/",
            "Server = https://mirrors.ustc.edu.cn/msys2/msys/`$arch/",
            "Server = https://mirrors.aliyun.com/msys2/msys/`$arch/",
            "Server = https://repo.msys2.org/msys/`$arch/"
        ) | Set-Content -Path $msysMirror -Encoding ASCII
    }
    $script:commands += [ordered]@{
        command = "Set-Msys2MirrorPreference"
        arguments = @($Root)
        exit_code = 0
        output = @("Updated mirrorlist.mingw and mirrorlist.msys for sandbox install.")
    }
}

$status = "not_installed"
$gfortran = Find-GFortran
if ($gfortran) {
    $status = "available"
    Record-GFortranToolVersions -GFortranPath $gfortran
} elseif (-not $Install) {
    $status = "blocked_install_not_requested"
} else {
    $installer = Join-Path $ToolchainDir "msys2-x86_64-latest.exe"
    if (Test-Path $installer) {
        $existingInstaller = Get-Item $installer
        if ($existingInstaller.Length -lt 1000000) {
            Remove-Item -LiteralPath $installer -Force
        }
    }
    $releaseApi = "https://api.github.com/repos/msys2/msys2-installer/releases/latest"
    $url = "https://github.com/msys2/msys2-installer/releases/latest/download/msys2-x86_64-latest.exe"

    try {
        $release = Invoke-RestMethod -Uri $releaseApi -UseBasicParsing
        $asset = @($release.assets | Where-Object { $_.name -match '^msys2-x86_64-.*\.exe$' } | Select-Object -First 1)
        if ($asset -and $asset.browser_download_url) {
            $url = $asset.browser_download_url
            $commands += [ordered]@{
                command = "Invoke-RestMethod"
                arguments = @($releaseApi)
                exit_code = 0
                output = @("selected_asset=$($asset.name)", "url=$url")
            }
        } else {
            $commands += [ordered]@{
                command = "Invoke-RestMethod"
                arguments = @($releaseApi)
                exit_code = -1
                output = @("No msys2-x86_64 exe asset found; falling back to static URL.")
            }
        }
    } catch {
        $commands += [ordered]@{
            command = "Invoke-RestMethod"
            arguments = @($releaseApi)
            exit_code = -1
            output = @($_.Exception.Message)
        }
    }

    for ($attempt = 1; $attempt -le 3 -and -not (Test-Path $installer); $attempt++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
            $commands += [ordered]@{
                command = "Invoke-WebRequest"
                arguments = @("attempt=$attempt", $url, $installer)
                exit_code = 0
                output = @("downloaded")
            }
        } catch {
            $commands += [ordered]@{
                command = "Invoke-WebRequest"
                arguments = @("attempt=$attempt", $url, $installer)
                exit_code = -1
                output = @($_.Exception.Message)
            }
            Start-Sleep -Seconds 3
        }
    }

    if (-not (Test-Path $installer)) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            $record = Invoke-LoggedCommand -Command $curl.Source -Arguments @(
                "-L",
                "--retry", "3",
                "--retry-delay", "5",
                "-o", $installer,
                $url
            )
            if ($record.exit_code -ne 0 -and (Test-Path $installer)) {
                Remove-Item -LiteralPath $installer -Force
            }
        }
    }

    if (Test-Path $installer) {
        $installerItem = Get-Item $installer
        if ($installerItem.Length -lt 1000000) {
            $preview = Get-Content $installer -Raw -ErrorAction SilentlyContinue
            $commands += [ordered]@{
                command = "installer-size-check"
                arguments = @($installer)
                exit_code = -1
                output = @("Installer is too small: $($installerItem.Length) bytes", "preview=$preview")
            }
            Remove-Item -LiteralPath $installer -Force
        }
    }

    if (Test-Path $installer) {
        $installRecord = Invoke-LoggedCommand -Command $installer -Arguments @("install", "--confirm-command", "--accept-messages", "--root", $MsysRoot)
        if ($installRecord.exit_code -ne 0 -and -not (Test-Path (Join-Path $MsysRoot "usr\bin\bash.exe"))) {
            Invoke-LoggedCommand -Command $installer -Arguments @("in", "--confirm-command", "--accept-licenses", "--root", $MsysRoot) | Out-Null
        }
    }

    $bash = Join-Path $MsysRoot "usr\bin\bash.exe"
    if (Test-Path $bash) {
        Set-Msys2MirrorPreference -Root $MsysRoot
        Invoke-LoggedCommand -Command $bash -Arguments @("-lc", "pacman -Sy --needed --noconfirm mingw-w64-x86_64-gcc-fortran mingw-w64-x86_64-gcc mingw-w64-x86_64-make") | Out-Null
    }

    $gfortran = Find-GFortran
    if ($gfortran) {
        $status = "available"
        Record-GFortranToolVersions -GFortranPath $gfortran
    } else {
        $status = "install_attempt_failed"
    }
}

$result = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    sandbox_root = $SandboxRoot
    install_requested = [bool]$Install
    msys_root = $MsysRoot
    status = $status
    gfortran = $gfortran
    commands = $commands
}

$jsonPath = Join-Path $LogsDir "msys2_gfortran_install.json"
$mdPath = Join-Path $LogsDir "msys2_gfortran_install.md"
$result | ConvertTo-Json -Depth 12 | Set-Content -Path $jsonPath -Encoding UTF8

$lines = @(
    "# MSYS2 gfortran Install/Probe",
    "",
    "- install_requested: $Install",
    "- status: $status",
    "- msys_root: $MsysRoot",
    "- gfortran: $gfortran",
    "",
    "## Commands",
    "",
    "| command | exit_code |",
    "| --- | --- |"
)
foreach ($cmd in $commands) {
    $lines += "| $($cmd.command) $($cmd.arguments -join ' ') | $($cmd.exit_code) |"
}
$lines | Set-Content -Path $mdPath -Encoding UTF8

Write-Output "Wrote $jsonPath"
Write-Output "Wrote $mdPath"
if ($status -eq "blocked_install_not_requested") {
    Write-Output "MSYS2/gfortran not found. Re-run with -Install only if toolchain installation is explicitly allowed."
}
