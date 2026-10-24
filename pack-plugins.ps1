$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'dist/plugins'
foreach ($source in @('plugins/desk-note', 'plugins/local-gallery', 'plugins/codex-companion')) {
    $name = Split-Path $source -Leaf
    & python (Join-Path $PSScriptRoot 'scripts/pack_plugin.py') (Join-Path $PSScriptRoot $source) (Join-Path $destination "$name.screen-plugin.zip")
    if ($LASTEXITCODE -ne 0) { throw "插件打包失败：$name" }
}
