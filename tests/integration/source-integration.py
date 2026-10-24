"""Real vendor SDK, HTTP SDKs and scheduler output; all traffic stays on loopback."""
import ast,io,json,os,socket,struct,subprocess,sys,tempfile,threading,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
tree=ast.parse((ROOT/'tests/support/note4_peer.py').read_text(encoding='utf-8'))
exec(compile(ast.Module(body=[next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Peer')],type_ignores=[]),'peer','exec'))
sys.path.insert(0,str(ROOT/'clients/screen-scheduler-client/python'))
from screen_scheduler import Device,OpenOptions,ImageFormat,SchedulerError
def wait(fn,seconds=14):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   result=fn()
   if result:return result
  except (OSError,ValueError,KeyError,TypeError):pass
  time.sleep(.08)
 raise AssertionError('condition timed out')
def main():
 opener=build_opener(ProxyHandler({}));checks=[];peer=Peer();children=[];clients=[]
 with tempfile.TemporaryDirectory(prefix='source-integration-',dir=TEMP) as tmp:
  tmp=Path(tmp);picture=tmp/'picture.png';Image.new('RGB',(400,300),'#526f79').save(picture)
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  url=f'http://127.0.0.1:{port}'
  process=subprocess.Popen([os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--port',str(port),'--config',str(tmp/'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);children.append(process)
  def fetch(base,path,method='GET',body=None,token=None,headers=None):
   h=dict(headers or {});
   if token:h['Authorization']='Bearer '+token
   if isinstance(body,dict):body=json.dumps(body).encode();h['Content-Type']='application/json'
   try:
    with opener.open(Request(base+path,data=body,headers=h,method=method),timeout=15) as r:return r.status,json.load(r)
   except HTTPError as e:return e.code,e.read().decode()
  state=lambda:fetch(url,'/control/state')[1]
  def command(op,id='',data=None):
   code,value=fetch(url,'/control/command','POST',{'op':op,'id':id,'data':data or {}},headers={'x-control-token':control});assert code==200,(code,value);return value
  try:
   control=wait(lambda:state()['token']);access=state()['access'];http='http://'+access['http'];key=access['api_key'];sdk=access['sdk']
   assert fetch(http,'/v1/sessions','POST',{'name':'拒绝未授权'})[0]==401;checks.append('http_registration_authentication')
   command('mode',data={'mode':'device'});command('connect',data={'target':f'127.0.0.1:{peer.address[1]}'})
   d=Device.open(OpenOptions(http,'Python 生图程序'),key);clients.append(d)
   r=d.submit(picture.read_bytes(),ImageFormat.Gray16)
   wait(lambda:d.receipt(r['sequence'])['state']=='displayed');assert peer.begins>0
   checks.append('python_http_sdk_to_scheduler_to_vendor_sdk_display_receipt')
   replay=d.submit(picture.read_bytes(),ImageFormat.Gray16,sequence=1);assert replay['revision']==r['revision']
   other=io.BytesIO();Image.new('RGB',(400,300),'black').save(other,format='PNG')
   try:d.submit(other.getvalue(),ImageFormat.Gray16,sequence=1);raise AssertionError('conflict accepted')
   except SchedulerError as e:assert e.status==409
   checks.append('http_idempotency_and_conflicting_replay_rejection')
   peer.key(1,501);event=d.next_event(timeout=4);assert event['key']=='Up' and event['revision']==r['revision'];checks.append('physical_key_returns_to_python_producer_with_shown_revision')
   assert fetch(http,f'/v1/sessions/{d.id}/events',token='wrong')[0]==401;checks.append('session_token_isolation')
   # Keep frames waiting while automatic switching is paused; old pending receipts must be superseded.
   command('global',data={'preempt':True,'paused':True});r2=d.submit(picture.read_bytes());r3=d.submit(other.getvalue());assert d.receipt(r2['sequence'])['state']=='superseded'
   q=state()['queue'];row=next(row for row in q['rows'] if row['id']==d.id)
   assert row['role']=='updating' and row['shown_revision']<row['revision'];checks.append('live_queue_and_pending_revision_supersession')
   command('global',data={'preempt':True,'paused':False});wait(lambda:d.receipt(r3['sequence'])['state']=='displayed')
   b=Device.open(OpenOptions(http,'未知结果替换'),key);clients.append(b)
   command('settings',b.id,{'priority':1,'bypass':True})
   peer.unknown=True;unknown=b.submit(picture.read_bytes());wait(lambda:state()['device']['blocked'])
   peer.key(2,551);assert d.next_event(timeout=.7) is None and b.next_event(timeout=.7) is None
   checks.append('unknown_replacement_blocks_keys_to_old_and_new_producers')
   peer.unknown=False;command('retry');wait(lambda:b.receipt(unknown['sequence'])['state']=='displayed');b.close()
   d.close();wait(lambda:not state()['external'])
   checks.append('explicit_http_close_removes_channel')
   # The original SDK package is used without modification, including its palette checks.
   original=subprocess.Popen([str(ROOT/'target/debug/examples/original_sdk.exe'),sdk,str(picture)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8');children.append(original)
   wait(lambda:any(e['transport']=='sdk' for e in state()['external']))
   wait(lambda:state()['current'] and not state()['device']['sending'])
   peer.key(2,601);out,err=original.communicate(timeout=15);assert original.returncode==0,(out,err);assert 'accepted by virtual gateway' in out and 'key Down' in out
   wait(lambda:not state()['external']);checks.append('unchanged_original_sdk_connect_show_palette_key_close')
   env=dict(os.environ);env['SCREEN_SCHEDULER_KEY']=key
   rust=subprocess.Popen([str(ROOT/'target/debug/examples/http_roundtrip.exe'),http,str(picture)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env);children.append(rust)
   wait(lambda:any(s['config']['name']=='Rust HTTP 回环' for s in state()['sources']))
   wait(lambda:state()['current'] and not state()['device']['sending'])
   peer.key(1,701);out,err=rust.communicate(timeout=15);assert rust.returncode==0,(out,err);assert 'key Up' in out and 'receipt displayed' in out;wait(lambda:not state()['external']);checks.append('rust_http_sdk_open_show_event_receipt_close')
   # Abandoned HTTP and UDP sources expire independently of task lifetime.
   abandoned=fetch(http,'/v1/sessions','POST',{'name':'HTTP 无心跳'},key)[1]
   peer.delay_until=time.monotonic()+18
   assert fetch(http,f'/v1/sessions/{abandoned["id"]}/frames/1','POST',picture.read_bytes(),abandoned['token'],{'x-image-format':'mono'})[0]==200
   wait(lambda:state()['device']['sending'])
   sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.settimeout(2);ip,p=sdk.split(':');dest=(ip,int(p))
   def packet(kind,connection,seq,body=b''):return b'ZL\x01'+bytes([kind])+struct.pack('>QI',connection,seq)+body
   sock.sendto(packet(1,0,1),dest);info=sock.recv(1200);connection=int.from_bytes(info[4:12],'big');name=b'UDP no heartbeat';sock.sendto(packet(2,connection,1,bytes([len(name)])+name),dest);assert sock.recv(1200)[16]==0
   sock.sendto(packet(15,connection,1),dest);assert sock.recv(1200)[16:]==bytes([0,255,255,127])
   sock.sendto(packet(8,connection,2,b'\0'),dest);assert sock.recv(1200)[16]==2
   checks.append('sdk_status_unknown_and_audio_explicitly_rejected')
   sock.sendto(packet(4,connection,3,b'\0'),dest);assert sock.recv(1200)[16]==0
   sock.sendto(packet(1,0,1),dest);info=sock.recv(1200);new_connection=int.from_bytes(info[4:12],'big');assert new_connection!=connection
   sock.sendto(packet(2,new_connection,1,bytes([len(name)])+name),dest);assert sock.recv(1200)[16]==0
   checks.append('closed_udp_endpoint_gets_fresh_connection_id')
   d=Device.open(OpenOptions(http,'保持心跳'),key);clients.append(d)
   print('checking 15-second lease expiry...',flush=True)
   wait(lambda:len(state()['external'])==1,seconds=19)
   assert state()['external'][0]['id']==d.id;checks.append('http_and_udp_lease_expiry_while_client_heartbeat_stays_online')
   assert state()['device']['sending'];checks.append('lease_cleanup_continues_during_slow_physical_refresh')
   wait(lambda:not state()['device']['sending']);assert state()['current'] is None
   checks.append('expired_producer_completion_does_not_restore_key_focus');d.close();sock.close()
   command('disconnect');command('stop');process.wait(8)
   result={'passed':len(checks),'checks':checks,'physical_device_tested':False};(RESULTS/'source-integration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
  except Exception:
   if process.poll() is None:process.terminate();process.wait(5)
   print(process.stderr.read().decode('utf-8',errors='replace'),file=sys.stderr)
   raise
  finally:
   for d in clients:
    try:d.close()
    except Exception:pass
   for child in children:
    if child.poll() is None:child.terminate();child.wait(5)
   peer.running=False;peer.socket.close()
if __name__=='__main__':main()
