"""Exercise multi-channel lifecycle and legacy migration against an isolated simulation host."""
import io,json,os,subprocess,tempfile,time,socket
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)

def wait(fn,seconds=18):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   value=fn()
   if value:return value
  except (OSError,ValueError,KeyError,TypeError,StopIteration):pass
  time.sleep(.08)
 raise AssertionError('condition timed out')

def main():
 checks=[];opener=build_opener(ProxyHandler({}))
 with tempfile.TemporaryDirectory(prefix='channels-test-',dir=TEMP) as d:
  tmp=Path(d);photos=tmp/'photos';photos.mkdir()
  for n,color in enumerate(['red','green','blue']):Image.new('RGB',(80,140),color).save(photos/f'{n}.png')
  config=tmp/'settings.json'
  def old(id,enabled=True):return [{'id':id,'name':'旧相册'+id,'priority':3,'min_ms':0,'hold_ms':0,'ttl_ms':0,'persistent':True,'enabled':enabled,'bypass':False,'format':'gray16','fit':'cover','boost':None,'revision':0,'updated_at':0,'order':0,'consumed':0},{'folder':str(photos),'interval_ms':1000,'shuffle':False,'fixed':False,'index':1,'selected':str(photos/'1.png'),'files':[str(p) for p in sorted(photos.iterdir())]}]
  config.write_text(json.dumps({'target':'','preempt':True,'api_key':'test','pools':[old('one'),old('two',False)]}),encoding='utf-8')
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  url=f'http://127.0.0.1:{port}';token='';process=None
  def call(path,body=None,raw=False):
   headers={}
   if body is not None:
    headers['x-control-token']=token
    if isinstance(body,dict):body=json.dumps(body).encode();headers['Content-Type']='application/json'
   try:
    with opener.open(Request(url+path,data=body,headers=headers),timeout=18) as r:
     data=r.read();return r.status,data if raw else json.loads(data)
   except HTTPError as e:return e.code,e.read()
  state=lambda:call('/control/state')[1]
  def command(op,id='',data=None):
   code,value=call('/control/command',{'op':op,'id':id,'data':data or {}});assert code==200,(code,value);return value
  def plugin_op(op,data=None):
   code,value=call('/control/plugins/local-gallery',{'op':op,'data':data or {}});assert code==200,(code,value);return value
  def start():return subprocess.Popen([os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--config',str(config),'--port',str(port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  try:
   process=start();token=wait(lambda:state()['token']);wait(lambda:len(state()['plugins'])==1 and len(state()['sources'])==2)
   plugin=lambda:state()['plugins'][0]
   wait(lambda:state()['current']);albums=plugin()['settings']['sources'];key=next(a['id'] for a in albums if a['enabled']);sid=plugin()['channels'][key]
   assert plugin()['id']=='local-gallery';assert plugin()['source'] is None
   assert len(plugin()['channels'])==2;assert sum(s['config']['enabled'] for s in state()['sources'])==1,[(s['config']['name'],s['config']['enabled']) for s in state()['sources']]
   assert all(a['fit']=='cover' for a in albums);assert plugin()['state']['albums'][key]['current']=='1.png'
   checks.append('legacy_pools_merge_to_one_plugin_preserving_selection_fit_disabled_state')
   before=plugin()['state']['albums'][key]['current'];wait(lambda:plugin()['state']['albums'][key]['current']!=before);checks.append('visible_album_advances_after_display_deadline')
   # A hidden album must not refresh revision or move selection.
   u=command('add',data={'name':'urgent','priority':1,'min_ms':0,'persistent':True})['id'];buf=io.BytesIO();Image.new('RGB',(400,300),'black').save(buf,format='PNG');assert call('/control/image/'+u,buf.getvalue())[0]==200
   wait(lambda:state()['current']['frame']['id']==u);wait(lambda:not plugin()['running']);before=plugin()['state']['albums'][key]['current'];rev=next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==sid)
   time.sleep(2.5);assert plugin()['state']['albums'][key]['current']==before;assert next(s['config']['revision'] for s in state()['sources'] if s['config']['id']==sid)==rev
   command('remove',u);wait(lambda:state()['current']['frame']['id']==sid);wait(lambda:plugin()['state']['albums'][key]['current']!=before);checks.append('hidden_album_pauses_and_resumes_after_actual_display')
   # Removing one source and adding another reconciles independent channels.
   values=plugin()['settings'];values['sources']=[next(a for a in albums if a['id']==key)]
   values['sources'].append({**values['sources'][0],'id':'new-album','name':'new album','mode':'固定一张'})
   plugin_op('settings',values);wait(lambda:set(plugin()['channels'])=={key,'new-album'})
   assert len(state()['sources'])==2;checks.append('source_edit_add_remove_reconciles_channels')
   assert call('/control/command',{'op':'remove','id':sid})[0]==400;assert plugin()['enabled'];assert len(plugin()['channels'])==2
   checks.append('single_channel_exit_cannot_disable_the_whole_plugin')
   command('settings',sid,{'priority':2});plugin_op('disable');assert not state()['sources'];assert plugin()['channels']=={}
   plugin_op('enable');wait(lambda:len(plugin()['channels'])==2);sid=plugin()['channels'][key];assert next(s['config']['priority'] for s in state()['sources'] if s['config']['id']==sid)==2
   checks.append('disable_cleans_all_channels_and_enable_restores_saved_rules')
   # Strict output contract must reject a plugin bypassing the author API.
   file=config.with_suffix('.plugins')/'packages/local-gallery/main.py';original=file.read_text(encoding='utf-8');file.write_text(original+'\n_original=handle\ndef handle(ctx,event):\n _original(ctx,event)\n for c in ctx._channels.values():\n  if c._shown:Image.new("RGB",(50,50)).save(c._output)\n',encoding='utf-8')
   plugin_op('run');wait(lambda:plugin()['error']);assert 'PNG' in plugin()['error'] or '400' in plugin()['error'] or 'limit' in plugin()['error'].lower();file.write_text(original,encoding='utf-8');checks.append('host_rejects_non_screen_sized_plugin_frames')
   command('reconnect_settings',data={'enabled':True,'window_seconds':12,'interval_seconds':2});assert state()['device']['reconnect']['enabled'];assert call('/control/command',{'op':'reconnect_settings','data':{'window_seconds':0}})[0]==400
   command('stop');process.wait(10);process=start();token=wait(lambda:state()['token']);wait(lambda:len(state()['plugins'])==1 and len(state()['sources'])==2)
   assert state()['device']['reconnect']=={'enabled':True,'window_seconds':12,'interval_seconds':2};assert state()['device']['reconnect_until'] is None
   assert len(list(config.with_suffix('.plugins').joinpath('migration-backups').iterdir()))==1
   checks.append('restart_preserves_reconnect_settings_and_migration_is_idempotent')
   command('stop');process.wait(10)
  except Exception:
   if process and process.poll() is None:process.terminate();process.wait(5)
   if process:print(process.stderr.read().decode('utf-8',errors='replace'))
   raise
  finally:
   if process and process.poll() is None:process.terminate();process.wait(5)
 result={'passed':len(checks),'checks':checks,'physical_device_tested':False};(RESULTS/'channels-integration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
