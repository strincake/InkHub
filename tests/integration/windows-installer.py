import tomllib
"""Silent per-user install/upgrade/uninstall regression in a disposable directory."""
import hashlib,json,os,socket,subprocess,tempfile,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
VERSION=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']['version']
OPENER=build_opener(ProxyHandler({}))
def wait(fn,seconds=20):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise AssertionError('installer test timed out')
def main():
    installer=ROOT/'dist/releases'/f'InkHub-{VERSION}-windows-x64-setup.exe'
    temp=ROOT/'artifacts/tmp';temp.mkdir(exist_ok=True,parents=True)
    checks=[]
    with tempfile.TemporaryDirectory(prefix='installer-check-',dir=temp) as directory:
        folder=Path(directory);app=folder/'安装目录 with spaces';profile=folder/'user-data';profile.mkdir()
        args=[str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/TASKS=','/DIR='+str(app),'/LOG='+str(folder/'install.log')]
        child=None
        try:
            subprocess.run(args,check=True,timeout=120)
            exe=app/'InkHub.exe';assert exe.is_file();assert (app/'runtime/python/python.exe').is_file()
            checks.append('current_user_silent_install_to_unicode_and_space_path')
            subprocess.run([os.sys.executable,str(ROOT/'tests/integration/packaged-runtime.py'),'--app',str(exe)],check=True,timeout=90)
            checks.append('installed_app_passes_isolated_runtime_and_autostart_checks')
            # Create persistent configuration using the installed application.
            env=dict(os.environ);env.update(LOCALAPPDATA=str(profile),USERPROFILE=str(folder/'fake-user'),PATH=str(Path(os.environ['SYSTEMROOT'])/'System32'))
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            base=f'http://127.0.0.1:{port}'
            child=subprocess.Popen([str(exe),'--no-browser','--no-tray','--port',str(port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],env=env,cwd=folder,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            def state():
                with OPENER.open(base+'/control/state',timeout=2) as r:return json.load(r)
            ready=wait(state)
            def post(path,body):
                with OPENER.open(Request(base+path,data=json.dumps(body).encode(),headers={'content-type':'application/json','x-control-token':ready['token']}),timeout=10) as r:return json.load(r)
            post('/control/plugins/desk-note',{'op':'settings','data':{'title':'升级保留的用户便签','notes':'用户内容','theme':'浅色','refresh_seconds':30,'show_clock':True}})
            post('/control/command',{'op':'stop','id':'','data':{}});child.wait(15);child=None
            settings=profile/'InkHub/settings.json';record=profile/'InkHub/settings.plugins/data/desk-note/record.json'
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [settings,record]}
            subprocess.run(args,check=True,timeout=120)
            assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==value for p,value in before.items())
            checks.append('same_version_upgrade_preserves_user_settings_and_plugin_data')
        finally:
            if child and child.poll() is None:child.kill();child.wait()
            uninstaller=app/'unins000.exe'
            if uninstaller.exists():
                subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(folder/'uninstall.log')],check=True,timeout=120)
                wait(lambda:not (app/'InkHub.exe').exists())
                def log_released():
                    log=folder/'uninstall.log';probe=folder/'uninstall-finished.log'
                    try:log.rename(probe);probe.rename(log);return True
                    except PermissionError:return False
                wait(log_released)

        assert (profile/'InkHub/settings.json').is_file()
        assert (profile/'InkHub/settings.plugins/data/desk-note/record.json').is_file()
        checks.append('uninstall_removes_application_and_preserves_user_data')
    out=ROOT/'artifacts/tests/integration';out.mkdir(parents=True,exist_ok=True)
    result={'passed':len(checks),'checks':checks,'physical_device_tested':False}
    (out/'windows-installer-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
