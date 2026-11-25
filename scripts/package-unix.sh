#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname -- "$0")/.."
platform="$1"
version=$(python3 -c 'import tomllib; print(tomllib.load(open("Cargo.toml","rb"))["package"]["version"])')
mkdir -p dist/releases
stage=$(mktemp -d "$(pwd)/dist/inkhub-stage.XXXXXX")
trap 'rm -r -- "$stage"' EXIT
app="$stage/InkHub"
mkdir -p "$app/assets/fonts" "$app/licenses"
python3 scripts/prepare-windows-assets.py --fonts-only
install -m 755 target/release/note4-screen-scheduler "$app/note4-screen-scheduler"
install -m 755 packaging/unix/run-inkhub.sh "$app/run-inkhub"
cp requirements.txt README.md "$app/"
mkdir -p "$app/python/plugin_kit"
cp python/*.py "$app/python/"
cp python/plugin_kit/*.py "$app/python/plugin_kit/"
cp artifacts/windows-runtime/fonts/NotoSansSC.ttf "$app/assets/fonts/"
cp artifacts/windows-runtime/licenses/NotoSansSC-OFL.txt "$app/licenses/"
cp LICENSE "$app/licenses/InkHub-MIT.txt"
cp THIRD_PARTY_NOTICES.md "$app/licenses/"
cp vendor/zectrix-local-push-sdk/LICENSE "$app/licenses/Zectrix-SDK-MIT.txt"
cp vendor/zectrix-local-push-sdk/LICENSES/Opus-COPYING.txt "$app/licenses/"
cp plugins/codex-companion/LICENSE "$app/licenses/Codex-companion-LICENSE.txt"
cp plugins/codex-companion/THIRD_PARTY_NOTICES.md "$app/licenses/Codex-companion-NOTICES.md"
printf '{"schema":1,"version":"%s","platform":"%s"}\n' "$version" "$platform" > "$app/runtime-layout.json"
name="InkHub-$version-$platform.tar.gz"
tar -czf "dist/releases/$name" -C "$stage" InkHub
(cd dist/releases && shasum -a 256 "$name" > "$name.sha256")
