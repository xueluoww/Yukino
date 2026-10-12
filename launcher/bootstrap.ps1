# Yukino 0.9 启动器：Python 检测 → 版本校验 → 缺失时询问是否下载 → 交给 setup.py
# 兼容 Windows PowerShell 5.1 与 PowerShell 7。
[CmdletBinding()]
param(
    [switch]$Check,                 # 只做检测并输出 JSON（供自检与排错）
    [switch]$SimulateMissingPython, # 诊断用：假装本机没有 Python，用来验证弹窗流程
    [switch]$NoBrowser,
    [switch]$Stop,                  # 关闭已在运行的游戏服务
    [string]$PackageRoot
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Minimum = [version]'3.10'
$script:Root = if ($PackageRoot) { (Resolve-Path -LiteralPath $PackageRoot).Path }
               else { (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path }
$script:SetupPy = Join-Path $script:Root 'launcher\setup.py'
$script:DownloadUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$script:DownloadPage = 'https://www.python.org/downloads/windows/'

function Get-PythonVersion {
    param([string]$Exe, [string[]]$Prefix = @())
    # 用 --version 而不是 -c：Windows PowerShell 5.1 在向原生命令传参时会吃掉
    # 参数里的双引号（PS 7 才修），"python -c "<code>"" 会被改写成语法错误的代码。
    # --version 不含引号，最稳；解析失败时再用不含双引号的 -c 兜一次。
    $base = @()
    foreach ($item in @($Prefix)) { if ($item) { $base += $item } }
    $attempts = @(
        ($base + @('--version')),
        ($base + @('-c', 'import sys;print(''%d.%d.%d''%sys.version_info[:3])'))
    )
    foreach ($argumentList in $attempts) {
        try {
            $out = & $Exe @argumentList 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
            $text = ($out | Select-Object -First 1).ToString().Trim()
            if ($text -match '(\d+)\.(\d+)\.(\d+)') {
                return [version]("$($Matches[1]).$($Matches[2]).$($Matches[3])")
            }
        } catch { }
    }
    return $null
}

function Find-Python {
    $candidates = New-Object System.Collections.ArrayList
    [void]$candidates.Add([pscustomobject]@{ Exe = 'py'; Prefix = @('-3'); Label = 'py -3' })
    [void]$candidates.Add([pscustomobject]@{ Exe = 'python'; Prefix = @(); Label = 'python' })
    [void]$candidates.Add([pscustomobject]@{ Exe = 'python3'; Prefix = @(); Label = 'python3' })

    $globs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        (Join-Path $env:ProgramFiles 'Python3*\python.exe'),
        'C:\Python3*\python.exe'
    )
    foreach ($pattern in $globs) {
        try {
            Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | ForEach-Object {
                    [void]$candidates.Add([pscustomobject]@{ Exe = $_.FullName; Prefix = @(); Label = $_.FullName })
                }
        } catch { }
    }

    $fallback = $null
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if (-not $command -and -not (Test-Path -LiteralPath $candidate.Exe)) {
            if ($env:YUKINO_DEBUG) { Write-Host "  [debug] 跳过 $($candidate.Label)（命令与路径都不存在）" }
            continue
        }
        $version = Get-PythonVersion -Exe $candidate.Exe -Prefix $candidate.Prefix
        if ($env:YUKINO_DEBUG) { Write-Host "  [debug] 候选 $($candidate.Label) -> 版本 '$version'" }
        if ($version) {
            $foundCandidate = [pscustomobject]@{ Exe = $candidate.Exe; Prefix = $candidate.Prefix; Version = $version; Label = $candidate.Label }
            if ($version -ge $Minimum) { return $foundCandidate }
            if (-not $fallback -or $version -gt $fallback.Version) { $fallback = $foundCandidate }
        }
    }
    return $fallback
}

function Show-Box {
    param([string]$Text, [string]$Title = 'Yukino 0.9', [string]$Kind = 'Information')
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $icon = [System.Windows.Forms.MessageBoxIcon]::$Kind
        $owner = New-Object System.Windows.Forms.Form
        $owner.TopMost = $true
        $owner.ShowInTaskbar = $false
        $owner.WindowState = 'Minimized'
        $owner.Show()
        $owner.Activate()
        [void][System.Windows.Forms.MessageBox]::Show($owner, $Text, $Title, [System.Windows.Forms.MessageBoxButtons]::OK, $icon)
        $owner.Close()
    } catch {
        Write-Host $Text
    }
}

function Ask-Box {
    param([string]$Text, [string]$Title = 'Yukino 0.9')
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $owner = New-Object System.Windows.Forms.Form
        $owner.TopMost = $true
        $owner.ShowInTaskbar = $false
        $owner.WindowState = 'Minimized'
        $owner.Show()
        $owner.Activate()
        $answer = [System.Windows.Forms.MessageBox]::Show($owner, $Text, $Title,
            [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        $owner.Close()
        return $answer
    } catch {
        Write-Host $Text
        return [System.Windows.Forms.DialogResult]::No
    }
}

function Get-Installer {
    $target = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
    if (Test-Path -LiteralPath $target) {
        $signature = Get-AuthenticodeSignature -LiteralPath $target
        if ($signature.Status -eq 'Valid' -and $signature.SignerCertificate.Subject -match 'Python Software Foundation') {
            return $target
        }
        Write-Host '缓存安装包签名无效，将重新下载；不会运行该文件。'
    }
    Write-Host '正在下载 Python 3.12.10 官方安装程序……（约 25 MB，来源 python.org）'
    $progress = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $script:DownloadUrl -OutFile $target -UseBasicParsing -TimeoutSec 600
        $signature = Get-AuthenticodeSignature -LiteralPath $target
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            Write-Host '下载文件未通过 Python 发布者签名校验，请从官方网页手动下载安装。'
            return $null
        }
        return $target
    } catch {
        Write-Host ("下载失败：" + $_.Exception.Message)
        return $null
    } finally {
        $ProgressPreference = $progress
    }
}

# ── 主流程 ──────────────────────────────────────────────────────────────
$found = $null
if (-not $SimulateMissingPython) { $found = Find-Python }

if ($Check) {
    if ($found) {
        $payload = [pscustomobject]@{
            ok = ($found.Version -ge $Minimum); python = $found.Version.ToString()
            path = $found.Label; minimum = $Minimum.ToString(); root = $script:Root
        }
        $payload | ConvertTo-Json -Compress
        if ($found.Version -ge $Minimum) { exit 0 } else { exit 1 }
    }
    [pscustomobject]@{ ok = $false; python = $null; minimum = $Minimum.ToString(); root = $script:Root } | ConvertTo-Json -Compress
    exit 1
}

if (-not $found) {
    $message = @"
Yukino 0.9 需要 Python 3.10 或更新版本，本机没有检测到。

· 选择“是”：自动下载 Python 3.12.10 官方安装程序（python.org），下载后由你手动完成安装。
  安装时请勾选 “Add python.exe to PATH”，装完重新双击“启动 Yukino0.9.bat”。
· 选择“否”：退出。你也可以自行到 $script:DownloadPage 下载安装。
"@
    $answer = Ask-Box -Text $message
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        Write-Host '已取消。安装 Python 后请重新运行“启动 Yukino0.9.bat”。'
        exit 1
    }
    $installer = Get-Installer
    if ($installer) {
        Write-Host "安装程序已保存到：$installer"
        try {
            Start-Process -FilePath $installer
            Show-Box -Text "安装程序已启动。`n`n请在安装界面勾选 “Add python.exe to PATH”，完成安装后重新双击“启动 Yukino0.9.bat”。"
        } catch {
            Show-Box -Text "无法自动启动安装程序，请手动运行：`n$installer" -Kind 'Warning'
        }
    } else {
        Show-Box -Text "自动下载失败。`n请手动打开 $script:DownloadPage 下载安装 Python 3.10 或更新版本。" -Kind 'Warning'
        Start-Process $script:DownloadPage
    }
    exit 1
}

if ($found.Version -lt $Minimum) {
    $message = @"
检测到 Python $($found.Version)（$($found.Label)），低于所需的 $Minimum。

· 选择“是”：下载 Python 3.12.10 官方安装程序并手动安装。
· 选择“否”：退出。
"@
    $answer = Ask-Box -Text $message
    if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
        $installer = Get-Installer
        if ($installer) { Start-Process -FilePath $installer }
        else { Start-Process $script:DownloadPage }
    }
    exit 1
}

Write-Host "已找到 Python $($found.Version)（$($found.Label)）"
$setupArguments = @()
if ($found.Prefix.Count -gt 0) { $setupArguments += $found.Prefix }
$setupArguments += @('-B', '-X', 'utf8', $script:SetupPy)
if ($NoBrowser) { $setupArguments += '--no-browser' }
if ($Stop) { $setupArguments += '--stop' }
& $found.Exe @setupArguments
exit $LASTEXITCODE
