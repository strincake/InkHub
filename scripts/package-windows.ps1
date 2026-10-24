param([switch]$SkipBuild)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
if(-not $SkipBuild){& (Join-Path $projectRoot 'build.ps1') -Release}
& python (Join-Path $PSScriptRoot 'prepare-windows-assets.py') --compiler
if($LASTEXITCODE -ne 0){throw '发布运行环境准备失败'}
& python (Join-Path $PSScriptRoot 'package-windows.py')
if($LASTEXITCODE -ne 0){throw 'Windows 安装程序生成失败'}
