"""Discarded render polling and stale queued-key regressions, temporary simulation host only."""
import io,json,os,socket,subprocess,tempfile,time,zipfile
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from PIL import Image
from integration import wait
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
CODE="""import time
def handle(ctx,event):
 if event['type']=='startup':
  ctx.state={'polls':0,'keys':0};ctx.show(ctx.canvas())
 elif event['type']=='interval':ctx.state['polls']+=1
 elif event['type']=='manual' and event.get('action')=='slow':
  ctx.require_visible();ctx.state['discarded']=True;ctx.trigger_after(1);time.sleep(1);ctx.show(ctx.canvas('black'))
 elif event['type']=='manual' and event.get('action')=='block':time.sleep(1.2)
 elif event['type']=='key':
  ctx.require_visible();ctx.state['keys']+=1;ctx.show(ctx.canvas('black'))
"""

def main():
 binary=Path(os.environ.get('SCREEN_SCHEDULER_TEST_BINARY',os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe'))))
 opener=build_opener(ProxyHandler({}));checks=[];process=None
 with tempfile.TemporaryDirectory(dir=TEMP,prefix='host-races-') as directory:
  tmp=Path(directory)
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  base=f'http://127.0.0.1:{port}'
  def call(path,body=None):
   headers={}
   if body is not None:
    if not isinstance(body,bytes):body=json.dumps(body).encode();headers['Content-Type']='application/json'
    headers['x-control-token']=token
   try:
    with opener.open(Request(base+path,data=body,headers=headers),timeout=15) as r:return json.loads(r.read())
   except HTTPError as error:raise AssertionError((path,error.code,error.read().decode("utf-8","replace"))) from error
  state=lambda:call('/control/state')
  plugin=lambda name:next(p for p in state()['plugins'] if p['id']==name)
  control=lambda name,op,data={}:call('/control/plugins/'+name,{'op':op,'data':data})
  command=lambda op,id='',data={}:call('/control/command',{'op':op,'id':id,'data':data})
  def settled(name):
   p=plugin(name);return not p['running'] and not p['pending']
  def upload(source,color):
   out=io.BytesIO();Image.new('RGB',(400,300),color).save(out,format='PNG');call('/control/image/'+source,out.getvalue())
  def shown(source,revision=None):
   s=state();return s['current'] and s['current']['frame']['id']==source and (revision is None or s['current']['frame']['revision']==revision) and not s['device']['sending']
  try:
   process=subprocess.Popen([str(binary),'--port',str(port),'--config',str(tmp/'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
   token=wait(lambda:state()['token'])
   for name,static in [('static-poll',True),('displayed-only',False)]:
    archive=io.BytesIO();triggers={'startup':True,'keys':True,'actions':[{'id':'slow','label':'slow'},{'id':'block','label':'block'}]}
    if static:triggers['interval_seconds']=2
    with zipfile.ZipFile(archive,'w') as z:
     z.writestr('plugin.json',json.dumps({'api_version':1,'id':name,'name':name,'version':'1','entry':'main.py','triggers':triggers,'source_defaults':{'persistent':True,'ttl_ms':0,'hold_ms':0,'min_ms':0}}));z.writestr('main.py',CODE)
    call('/control/plugins/install',archive.getvalue());control(name,'enable');source=wait(lambda:plugin(name)['source']);wait(lambda:shown(source));wait(lambda:settled(name))
    before=plugin(name)['last_run'];control(name,'run',{'action':'slow'});wait(lambda:plugin(name)['running'])
    other=command('add',data={'name':'preempt','priority':1,'bypass':True,'min_ms':0,'hold_ms':0,'ttl_ms':0})['id'];upload(other,'red');wait(lambda:shown(other))
    wait(lambda:plugin(name)['last_run']!=before and settled(name));assert 'discarded' not in plugin(name)['state']
    if static:
     wait(lambda:plugin(name)['state']['polls']>=1,seconds=5);checks.append('discarded_visible_render_preserves_static_background_poll')
    else:
     last=plugin(name)['last_run'];time.sleep(1.7);assert plugin(name)['last_run']==last and plugin(name)['state']['polls']==0;checks.append('discarded_displayed_only_render_does_not_keep_dynamic_timer')
    command('remove',other);wait(lambda:shown(source));wait(lambda:settled(name))
    if not static:
     original=state()['current']['frame']['revision'];control(name,'run',{'action':'block'});wait(lambda:plugin(name)['running'])
     command('key',data={'key':'Down'});wait(lambda:plugin(name)['pending']>=1)
     upload(source,'blue');wait(lambda:shown(source,original+1));wait(lambda:settled(name));time.sleep(.3)
     assert plugin(name)['state']['keys']==0,plugin(name)['state']
     assert shown(source,original+1),state()['current'];checks.append('queued_key_for_old_revision_discards_state_and_picture_before_commit')
    control(name,'disable')
   command('stop');process.wait(timeout=10)
   print(json.dumps({'passed':len(checks),'checks':checks,'physical_device_tested':False},indent=2))
  finally:
   if process and process.poll() is None:process.kill();process.wait()
   if process and process.stderr:
    error=process.stderr.read().decode('utf-8','replace')
    if error:print(error)
if __name__=='__main__':main()
