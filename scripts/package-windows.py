"""Stage and compile the user-level Windows x64 installer from pinned assets."""
from pathlib import Path
import hashlib,json,shutil,subprocess,tomllib,zipfile
ROOT=Path(__file__).resolve().parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    version=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']['version']
    stage=ROOT/'artifacts/package/windows-x64'/version
    if stage.exists():
        assert stage.resolve().is_relative_to((ROOT/'artifacts/package').resolve())
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy2(ROOT/'target/release/note4-screen-scheduler.exe',stage/'InkHub.exe')
    shutil.copytree(ROOT/'python',stage/'python',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'plugins/local-gallery',stage/'plugins/local-gallery',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'artifacts/windows-runtime/python',stage/'runtime/python')
    (stage/'assets/fonts').mkdir(parents=True)
    shutil.copy2(ROOT/'artifacts/windows-runtime/fonts/NotoSansSC.ttf',stage/'assets/fonts/NotoSansSC.ttf')
    for dll in (stage/'runtime/python').glob('vcruntime*.dll'):shutil.copy2(dll,stage/dll.name)
    shutil.copytree(ROOT/'artifacts/windows-runtime/licenses',stage/'licenses')
    shutil.copy2(ROOT/'artifacts/tools/inno/license.txt',stage/'licenses/Inno-Setup-LICENSE.txt')
    for source,name in [('LICENSE','InkHub-MIT.txt'),('THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md'),('vendor/zectrix-local-push-sdk/LICENSE','Zectrix-SDK-MIT.txt'),('vendor/zectrix-local-push-sdk/LICENSES/Opus-COPYING.txt','Opus-COPYING.txt'),('plugins/codex-companion/LICENSE','Codex-companion-LICENSE.txt'),('plugins/codex-companion/THIRD_PARTY_NOTICES.md','Codex-companion-NOTICES.md')]:shutil.copy2(ROOT/source,stage/'licenses'/name)
    shutil.copy2(ROOT/'packaging/windows/InkHub.ico',stage/'assets/InkHub.ico')
    (stage/'runtime-layout.json').write_text(json.dumps({'schema':1,'version':version,'platform':'windows-x64','python':'runtime/python/python.exe'},indent=2)+'\n',encoding='utf-8')
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    source_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    manifest={p.relative_to(stage).as_posix():digest(p) for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'package-manifest.json').write_text(json.dumps({'version':version,'source_commit':source_commit,'source_dirty':source_dirty,'files':manifest},indent=2)+'\n',encoding='utf-8')
    output=ROOT/'dist/releases';output.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(ROOT/'artifacts/tools/inno/ISCC.exe'),'/Qp','/DAppVersion='+version,'/DSourceDir='+str(stage),'/DOutputDir='+str(output),str(ROOT/'packaging/windows/InkHub.iss')],check=True)
    installer=output/f'InkHub-{version}-windows-x64-setup.exe'
    archive=output/f'InkHub-{version}-windows-x64-portable.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,'InkHub/'+p.relative_to(stage).as_posix())
    (output/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in [installer,archive]),encoding='utf-8')
    print(json.dumps({'version':version,'installer':str(installer),'portable':str(archive),'staged_app':str(stage),'signed':False},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
