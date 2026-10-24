"""Local-only plugin lifecycle, worker reliability and persistence checks."""
import io,json,os,socket,subprocess,tempfile,time,zipfile
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
def wait(fn,seconds=12):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   value=fn()
   if value:return value
  except (OSError,KeyError,ValueError,TypeError):pass
  time.sleep(.1)
 raise AssertionError('condition timed out')
def package(id,code):
 data=io.BytesIO()
 with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('plugin.json',json.dumps({'api_version':1,'id':id,'name':id,'version':'1','entry':'main.py','triggers':{'startup':True}}));z.writestr('main.py',code)
 return data.getvalue()
def main():
 checks=[];opener=build_opener(ProxyHandler({}));process=None
 with tempfile.TemporaryDirectory(prefix='plugin-test-',dir=TEMP) as d:
  tmp=Path(d);config=tmp/'settings.json'
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  url=f'http://127.0.0.1:{port}'
  def start():
   env=dict(os.environ);env['SCREEN_SCHEDULER_KEY']='SECRET_MUST_NOT_BE_INHERITED';return subprocess.Popen([os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--port',str(port),'--config',str(config),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=env)
  def call(path,body=None,auth=True,raw=False):
   headers={}
   if body is not None:
    if isinstance(body,dict):body=json.dumps(body).encode();headers['Content-Type']='application/json'
    if auth:headers['x-control-token']=token
   try:
    with opener.open(Request(url+path,data=body,headers=headers),timeout=20) as r:
     content=r.read();return r.status,content if raw else json.loads(content)
   except HTTPError as e:return e.code,e.read()
  state=lambda:call('/control/state')[1]
  plugin=lambda id:next((p for p in state()['plugins'] if p['id']==id),None)
  def cmd(id,op,data=None):
   code,value=call('/control/plugins/'+id,{'op':op,'data':data or {}});assert code==200,(code,value);return value
  def settled(id):
   p=plugin(id);return p and p['last_run'] is not None and not p['running'] and not p['pending']
  try:
   process=start();token=wait(lambda:state()['token']);sample=(ROOT/'dist/plugins/desk-note.screen-plugin.zip').read_bytes()
   assert call('/control/plugins/install',sample,auth=False)[0]==403
   assert call('/control/plugins/install',sample)[0]==200;assert not plugin('desk-note')['enabled'];assert len(state()['sources'])==0
   checks.append('trusted_zip_install_requires_auth_and_does_not_execute')
   assert call('/control/plugins/install',sample)[0]==400;checks.append('duplicate_install_does_not_overwrite')
   cmd('desk-note','enable');wait(lambda:settled('desk-note'));wait(lambda:state()['current'] is not None)
   source=plugin('desk-note')['source'];assert state()['queue']['rows'][0]['transport']=='plugin';checks.append('startup_trigger_registers_source_and_displays')
   old=next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==source)
   cmd('desk-note','run',{'action':'next-note'});wait(lambda:next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==source)>old)
   checks.append('registered_manual_action_generates_new_state')
   wait(lambda:not state()['device']['sending']);time.sleep(.25)
   old=next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==source)
   assert call('/control/command',{'op':'key','data':{'key':'Down'}})[0]==200
   wait(lambda:next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==source)>old);checks.append('displayed_plugin_receives_key_trigger')
   values=dict(plugin('desk-note')['settings']);values['title']='我的私人便签';values['refresh_seconds']=5
   cmd('desk-note','settings',values);wait(lambda:settled('desk-note'))
   bad=dict(values);bad['refresh_seconds']='wrong';assert call('/control/plugins/desk-note',{'op':'settings','data':bad})[0]==400
   checks.append('typed_settings_and_settings_changed_trigger')
   old=plugin('desk-note')['last_run'];wait(lambda:plugin('desk-note')['last_run']>old,seconds=8);checks.append('dynamic_trigger_after_executes_without_external_program')
   assert call('/control/command',{'op':'settings','id':source,'data':{'priority':2}})[0]==200
   exported=opener.open(Request(url+'/control/plugins/desk-note/export',headers={'x-control-token':token}),timeout=10).read()
   with zipfile.ZipFile(io.BytesIO(exported)) as z:assert 'plugin.json' in z.namelist() and all('record.json' not in n and not n.startswith('data/') for n in z.namelist());assert '我的私人便签'.encode() not in exported
   checks.append('share_export_contains_code_not_private_settings_or_state')
   error=package('broken','def handle(ctx,event):\n raise RuntimeError("expected isolated failure")')
   assert call('/control/plugins/install',error)[0]==200;cmd('broken','enable');wait(lambda:plugin('broken')['error']);assert plugin('desk-note')['enabled'];checks.append('plugin_failure_isolated_and_reported')
   env=package('env-check','import os\ndef handle(ctx,event):\n ctx.state["secret_inherited"]="SCREEN_SCHEDULER_KEY" in os.environ')
   assert call('/control/plugins/install',env)[0]==200;cmd('env-check','enable');wait(lambda:settled('env-check'))
   record=json.loads(config.with_suffix('.plugins').joinpath('data/env-check/record.json').read_text(encoding='utf-8'));assert record['state']['secret_inherited'] is False;checks.append('worker_does_not_inherit_host_api_key_environment')
   slow=package('slow','import time\ndef handle(ctx,event):\n time.sleep(60)')
   assert call('/control/plugins/install',slow)[0]==200;cmd('slow','enable');wait(lambda:plugin('slow')['running']);cmd('slow','disable');wait(lambda:not plugin('slow')['running'],seconds=4);assert plugin('slow')['source'] is None
   checks.append('disable_cancels_worker_and_revokes_source')
   cmd('slow','enable');print('checking worker 15-second deadline...',flush=True);wait(lambda:plugin('slow')['error'],seconds=18);assert '15' in plugin('slow')['error'];checks.append('worker_timeout_keeps_host_responsive')
   for id in ['slow','broken','env-check']:cmd(id,'uninstall');assert plugin(id) is None
   checks.append('uninstall_stops_and_removes_only_selected_plugins')
   before=plugin('desk-note')['settings'];call('/control/command',{'op':'stop'});process.wait(8);process=start();token=wait(lambda:state()['token']);wait(lambda:settled('desk-note'))
   assert plugin('desk-note')['settings']==before and plugin('desk-note')['enabled'];source=plugin('desk-note')['source'];assert next(s['config']['priority'] for s in state()['sources'] if s['config']['id']==source)==2
   checks.append('restart_restores_enabled_plugin_settings_state_and_display_rules')
   cmd('desk-note','uninstall');assert not config.with_suffix('.plugins').joinpath('packages/desk-note').exists();assert not config.with_suffix('.plugins').joinpath('data/desk-note').exists()
   assert call('/control/plugins/install',exported)[0]==200;assert plugin('desk-note')['settings']['title']!='我的私人便签';checks.append('exported_zip_reinstalls_cleanly_without_personal_data')
   call('/control/command',{'op':'stop'});process.wait(8)
   result={'passed':len(checks),'checks':checks,'physical_device_tested':False};(RESULTS/'plugin-integration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
  except Exception:
   if process and process.poll() is None:process.terminate();process.wait(5)
   if process:print(process.stderr.read().decode('utf-8',errors='replace'))
   raise
  finally:
   if process and process.poll() is None:process.terminate();process.wait(5)
if __name__=='__main__':main()
