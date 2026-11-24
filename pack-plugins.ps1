$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'dist/plugins'
foreach ($name in Get-Content (Join-Path $PSScriptRoot 'packaging/builtin-plugins.txt')) {
    if (-not $name) { continue }
    $source = "plugins/$name"
    & python (Join-Path $PSScriptRoot 'scripts/pack_plugin.py') (Join-Path $PSScriptRoot $source) (Join-Path $destination "$name.screen-plugin.zip")
    if ($LASTEXITCODE -ne 0) { throw "插件打包失败：$name" }
}
