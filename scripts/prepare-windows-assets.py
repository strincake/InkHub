"""Prepare SHA256-locked Windows x64 runtime; --compiler also bootstraps local ISCC."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'packaging/windows/runtime-lock.json'
CACHE = ROOT / 'artifacts/cache/windows'
OUTPUT = ROOT / 'artifacts/windows-runtime'


def download(asset):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / asset['filename']
    if not path.exists():
        temporary = path.with_suffix(path.suffix + '.download')
        try:
            with urllib.request.urlopen(asset['url'], timeout=120) as source, temporary.open('wb') as target:
                shutil.copyfileobj(source, target)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != asset['sha256']:
                raise RuntimeError('SHA256 mismatch: ' + asset['filename'])
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
        raise RuntimeError('SHA256 mismatch: ' + asset['filename'])
    return path


def unpack(path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename.replace('\\', '/'))
            if name.is_absolute() or '..' in name.parts or ':' in entry.filename:
                raise RuntimeError('Unsafe archive member: ' + entry.filename)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Archive symlink is not allowed')
            target = (destination / str(name)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError('Archive traversal')
        archive.extractall(destination)


def compiler(asset, chinese_asset):
    installer = download(asset)
    # Validate the signed official executable before running even when already cached.
    quoted = str(installer).replace("'", "''")
    check = r"$ErrorActionPreference='Stop'; $env:PSModulePath=$env:SystemRoot + '\System32\WindowsPowerShell\v1.0\Modules'; Import-Module Microsoft.PowerShell.Security; $s=Get-AuthenticodeSignature -LiteralPath '" + quoted + "'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Pyrsys B[.]V[.]') { throw 'Inno Setup publisher signature validation failed' }; $s.SignerCertificate.Subject"
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', check], check=True)
    directory = ROOT / 'artifacts/tools/inno'
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / 'ISCC.exe').exists():
        subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/CURRENTUSER', '/NOICONS', '/TASKS=', '/DIR=' + str(directory)], check=True)
    if not (directory / 'ISCC.exe').is_file():
        raise RuntimeError('Inno Setup did not produce ISCC.exe')
    languages = directory / 'Languages'
    languages.mkdir(parents=True, exist_ok=True)
    shutil.copy2(download(chinese_asset), languages / 'ChineseSimplified.isl')
    print('ISCC:', directory / 'ISCC.exe')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', action='store_true')
    args = parser.parse_args()
    assets = json.loads(LOCK.read_text(encoding='utf-8'))['assets']
    python = OUTPUT / 'python'
    unpack(download(assets['python']), python)
    packages = python / 'Lib/site-packages'
    unpack(download(assets['pillow']), packages)
    pth_files = list(python.glob('python*._pth'))
    if len(pth_files) != 1:
        raise RuntimeError('Expected exactly one embedded Python _pth file')
    pth = pth_files[0]
    pth.write_text(pth.stem + '.zip\n.\nLib/site-packages\nimport site\n', encoding='utf-8')
    fonts = OUTPUT / 'fonts'
    licenses = OUTPUT / 'licenses'
    fonts.mkdir(parents=True, exist_ok=True)
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(download(assets['font']), fonts / 'NotoSansSC.ttf')
    shutil.copy2(download(assets['font_license']), licenses / 'NotoSansSC-OFL.txt')
    for license_file in python.glob('*LICENSE*'):
        if license_file.is_file():
            shutil.copy2(license_file, licenses / ('Python-' + license_file.name))
    for license_file in packages.glob('pillow-*.dist-info/licenses/*'):
        if license_file.is_file():
            shutil.copy2(license_file, licenses / ('Pillow-' + license_file.name))
    subprocess.run([str(python / 'python.exe'), '-I', '-c', 'import sys; from PIL import Image, ImageFont; print(sys.version); print("Pillow", Image.__version__); Image.new("RGB", (2, 2)).save("' + str(OUTPUT / 'pillow-smoke.png').replace('\\', '/') + '"); ImageFont.truetype("' + str(fonts / 'NotoSansSC.ttf').replace('\\', '/') + '", 16)'], check=True)
    (OUTPUT / 'pillow-smoke.png').unlink()
    if args.compiler:
        compiler(assets['inno'], assets['inno_chinese'])
    print('Runtime:', OUTPUT)


if __name__ == '__main__':
    main()
