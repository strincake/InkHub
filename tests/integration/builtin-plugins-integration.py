"""Release-only builtin bootstrap regression; synthetic config and loopback listeners."""
import json,os,shutil,socket,subprocess,tempfile,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
TEMP=ROOT/'artifacts/tmp';TEMP.mkdir(parents=True,exist_ok=True)
BINARY=Path(os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/release/note4-screen-scheduler.exe')))
IDS={'desk-note','local-gallery','codex-companion'}
OPENER=build_opener(ProxyHandler({}))
def wait(fn):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError,KeyError):pass
        time.sleep(.08)
    raise AssertionError('isolated host did not become ready')
def run(config,check):
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    child=subprocess.Popen([str(BINARY),'--port',str(port),'--config',str(config),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    def state():
        with OPENER.open(base+'/control/state',timeout=3) as r:return json.load(r)
    def command(id,op):
        current=state();body=json.dumps({'op':op,'data':{}}).encode()
        with OPENER.open(Request(base+'/control/plugins/'+id,data=body,headers={'content-type':'application/json','x-control-token':current['token']}),timeout=10) as r:return json.load(r)
    try:
        ready=wait(state);check(state,command,ready)
    finally:
        if child.poll() is None:
            try:
                current=state();body=json.dumps({'op':'stop','id':'','data':{}}).encode()
                with OPENER.open(Request(base+'/control/command',data=body,headers={'content-type':'application/json','x-control-token':current['token']}),timeout=5):pass
                child.wait(10)
            finally:
                if child.poll() is None:child.kill();child.wait()
        error=child.stderr.read().decode('utf-8','replace')
        if child.returncode:raise AssertionError(error)
def main():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='builtin-release-',dir=TEMP) as folder:
        config=Path(folder)/'settings.json'
        def fresh(state,command,ready):
            plugins={p['id']:p for p in ready['plugins']}
            assert set(plugins)==IDS,sorted(plugins)
            assert all(not p['enabled'] and p['last_run'] is None for p in plugins.values())
            assert ready['sources']==[] and ready['current'] is None
        run(config,fresh);checks.append('fresh_release_installs_three_builtins_disabled_without_executing')
        def user_edit(state,command,ready):
            command('desk-note','enable');wait(lambda:next(p for p in state()['plugins'] if p['id']=='desk-note')['last_run'] is not None)
            command('desk-note','disable');command('local-gallery','uninstall')
        run(config,user_edit)
        def restart(state,command,ready):
            plugins={p['id']:p for p in ready['plugins']}
            assert set(plugins)==IDS-{'local-gallery'}
            assert plugins['desk-note']['enabled'] is False
            assert plugins['codex-companion']['enabled'] is False
        run(config,restart);checks.append('restart_preserves_disable_and_uninstall_without_reinstall')
    with tempfile.TemporaryDirectory(prefix='builtin-existing-',dir=TEMP) as folder:
        config=Path(folder)/'settings.json';package=config.with_suffix('.plugins')/'packages/desk-note'
        shutil.copytree(ROOT/'plugins/desk-note',package)
        manifest=json.loads((package/'plugin.json').read_text(encoding='utf-8'));manifest['name']='用户保留便签';manifest['version']='9.9.9'
        (package/'plugin.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        def existing(state,command,ready):
            plugins={p['id']:p for p in ready['plugins']};assert set(plugins)==IDS
            assert plugins['desk-note']['manifest']['name']=='用户保留便签'
            assert plugins['desk-note']['manifest']['version']=='9.9.9'
            assert all(not p['enabled'] for p in plugins.values())
        run(config,existing);checks.append('first_bootstrap_preserves_existing_same_id_package')
    result={'passed':len(checks),'checks':checks,'physical_device_tested':False}
    out=ROOT/'artifacts/tests/integration';out.mkdir(parents=True,exist_ok=True)
    (out/'builtin-plugins-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
