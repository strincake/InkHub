import tomllib
"""Verify the staged/installed app without developer Python or source-path resources."""
import argparse,io,json,os,socket,subprocess,tempfile,time,winreg
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
VERSION=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']['version']
OPENER=build_opener(ProxyHandler({}))
RUN=r'Software\Microsoft\Windows\CurrentVersion\Run'
def wait(fn,seconds=20):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError,KeyError):pass
        time.sleep(.08)
    raise AssertionError('packaged runtime timed out')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,default=ROOT/'artifacts/package/windows-x64'/VERSION/'InkHub.exe');args=parser.parse_args();app=args.app.resolve()
    temp=ROOT/'artifacts/tmp';temp.mkdir(parents=True,exist_ok=True)
    checks=[]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN) as key:
        try:original=winreg.QueryValueEx(key,'InkHub')
        except FileNotFoundError:original=None
    with tempfile.TemporaryDirectory(prefix='packaged-runtime-',dir=temp) as directory:
        folder=Path(directory);profile=folder/'profile';profile.mkdir();user=folder/'user';user.mkdir()
        env=dict(os.environ);env.update(LOCALAPPDATA=str(profile),USERPROFILE=str(user),PATH=str(Path(os.environ['SYSTEMROOT'])/'System32'),PYTHONDONTWRITEBYTECODE='1')
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        child=None
        def start():return subprocess.Popen([str(app),'--no-browser','--port',str(port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],cwd=folder,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def state():
            with OPENER.open(base+'/control/state',timeout=3) as r:return json.load(r)
        def post(path,body):
            current=state()
            with OPENER.open(Request(base+path,data=json.dumps(body).encode(),headers={'content-type':'application/json','x-control-token':current['token']}),timeout=15) as r:return json.load(r)
        def command(op,data=None):return post('/control/command',{'op':op,'data':data or {},'id':''})
        def plugin(id,op):return post('/control/plugins/'+id,{'op':op,'data':{}})
        def stop():
            if child and child.poll() is None:command('stop');child.wait(15)
        try:
            child=start();ready=wait(state)
            assert ready['application']['packaged'] and ready['application']['autostart_supported']
            assert {p['id'] for p in ready['plugins']}=={'desk-note','local-gallery','codex-companion'}
            assert all(not p['enabled'] and p['last_run'] is None for p in ready['plugins'])
            assert (profile/'InkHub/settings.json').is_file()
            assert not (app.parent/'settings.json').exists()
            checks.append('isolated_install_uses_own_python_and_per_user_data_without_system_python')
            duplicate=subprocess.run([str(app),'--no-browser','--autostart','--port',str(port)],cwd=folder,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10)
            assert duplicate.returncode==0 and child.poll() is None
            checks.append('second_launch_reuses_existing_instance_without_port_conflict')
            plugin('desk-note','enable');wait(lambda:state()['current'])
            with OPENER.open(base+'/control/image/'+next(p['source'] for p in state()['plugins'] if p['id']=='desk-note')) as r:
                assert Image.open(io.BytesIO(r.read())).size==(400,300)
            checks.append('bundled_python_pillow_font_and_plugin_worker_render_400x300')
            command('application_settings',{'autostart':True})
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN) as key:registered=winreg.QueryValueEx(key,'InkHub')[0]
            assert registered==f'"{app}" --autostart',registered
            assert state()['application']['autostart'] is True
            command('application_settings',{'autostart':False});assert state()['application']['autostart'] is False
            checks.append('autostart_settings_write_and_remove_current_user_run_entry')
            plugin('desk-note','disable');plugin('local-gallery','uninstall');stop()
            child=start();ready=wait(state)
            assert {p['id'] for p in ready['plugins']}=={'desk-note','codex-companion'}
            assert all(not p['enabled'] for p in ready['plugins'])
            checks.append('restart_preserves_user_plugin_choices')
            stop()
            # A missing packaged helper must fail; it must not silently use the developer source tree.
            helper=app.parent/'python/plugin_tools.py';backup=helper.with_suffix('.py.test-backup');helper.rename(backup)
            try:
                with socket.socket() as s:s.bind(('127.0.0.1',0));bad_port=s.getsockname()[1]
                bad=subprocess.run([str(app),'--no-browser','--no-tray','--config',str(folder/'new/settings.json'),'--port',str(bad_port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],cwd=folder,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15)
                assert bad.returncode!=0
            finally:backup.rename(helper)
            checks.append('missing_packaged_resource_does_not_fall_back_to_source_checkout')
        finally:
            if child and child.poll() is None:
                try:stop()
                except Exception:child.kill();child.wait()
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN) as key:
                if original is None:
                    try:winreg.DeleteValue(key,'InkHub')
                    except FileNotFoundError:pass
                else:winreg.SetValueEx(key,'InkHub',0,original[1],original[0])
    result={'passed':len(checks),'checks':checks,'system_python_hidden':True,'physical_device_tested':False,'interactive_tray_menu_tested':False}
    out=ROOT/'artifacts/tests/integration';out.mkdir(parents=True,exist_ok=True);(out/'packaged-runtime-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
