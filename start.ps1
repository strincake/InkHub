param(
    [switch]$Build,
    [switch]$Release,
    [switch]$NoBrowser,
    [ValidateRange(1, 65535)][int]$Port = 38476,
    [string]$Config = (Join-Path $PSScriptRoot 'settings.json'),
    [string]$HttpBind = '127.0.0.1:38477',
    [string]$SdkBind = '127.0.0.1:32342'
)
$ErrorActionPreference = 'Stop'
if ($Build) { & (Join-Path $PSScriptRoot 'build.ps1') -Release:$Release }
$profile = if ($Release) { 'release' } else { 'debug' }
$schedulerBinary = Join-Path $PSScriptRoot "target/$profile/note4-screen-scheduler.exe"
if (-not (Test-Path -LiteralPath $schedulerBinary)) {
    throw "没有找到构建结果：$schedulerBinary。请先运行 ./build.ps1，或使用 ./start.ps1 -Build。"
}
$schedulerUrl = "http://127.0.0.1:$Port"
$occupied = $false
try { $null = Invoke-WebRequest "$schedulerUrl/control/state" -TimeoutSec 2; $occupied = $true } catch {}
if ($occupied) { throw "管理端口 $Port 已有服务运行。请先从原网页退出旧实例，避免打开其他目录中的宿主。" }
$schedulerProcess = Start-Process -FilePath $schedulerBinary -ArgumentList @('--port', "$Port", '--config', ('"' + $Config + '"'), '--http-bind', $HttpBind, '--sdk-bind', $SdkBind) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$schedulerReady = $false
for ($attempt = 0; $attempt -lt 100; $attempt++) {
    if ($schedulerProcess.HasExited) { throw '宿主已退出，请检查管理端口或接入端口是否被占用。' }
    try {
        $schedulerState = Invoke-RestMethod "$schedulerUrl/control/state" -TimeoutSec 1
        $schedulerReady = $null -ne $schedulerState.device
        if ($schedulerReady) { break }
    } catch {}
    Start-Sleep -Milliseconds 200
}
if (-not $schedulerReady) { throw "服务尚未就绪，请检查进程 $($schedulerProcess.Id)。" }
Write-Output "墨枢已启动：$schedulerUrl"
if (-not $NoBrowser) { Start-Process $schedulerUrl }
