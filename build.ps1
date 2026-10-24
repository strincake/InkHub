param([switch]$Release)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw '未找到 Cargo。请安装 Rust stable（Windows MSVC 工具链），并在开发者终端中重试。'
}
$buildArguments = @('build', '--locked', '--manifest-path', (Join-Path $PSScriptRoot 'Cargo.toml'), '--target-dir', (Join-Path $PSScriptRoot 'target'))
if ($Release) { $buildArguments += '--release' }
& cargo @buildArguments
if ($LASTEXITCODE -ne 0) { throw '构建失败，请检查上方编译信息。Windows 还需要 C++ Build Tools 与 CMake。' }
