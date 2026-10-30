"""Real SDK reconnect control, using only a loopback UDP fake device."""
import json,os,socket,struct,subprocess,tempfile,threading,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
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
  except (OSError,ValueError):pass
  time.sleep(.05)
 raise AssertionError('timeout')

def main():
 peer=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);peer.bind(('127.0.0.1',0));peer.settimeout(.1)
 client=None;answer=True;running=True;opens=0
 def packet(kind,seq,body):return b'ZL'+bytes([1,kind])+struct.pack('>QI',0x1122334455667788,seq)+body
 def serve():
  nonlocal client,opens
  while running:
   try:raw,addr=peer.recvfrom(2048)
   except OSError:continue
   if len(raw)<16 or raw[3]&128:continue
   kind=raw[3];seq=struct.unpack('>I',raw[12:16])[0]
   if kind==1:opens+=1
   if not answer:continue
   body=b'\0'
   if kind==1:body+=bytes([0,12])+b'aabbccddeeff'+bytes([4])+b'test'+bytes([1,144,1,44,0,0,0,0,0,0,0,0])
   elif kind==2:client=addr
   elif kind==16:body=bytes([0,0,85,170,255])+bytes(n*17 for n in range(16))
   peer.sendto(packet(kind|128,seq,body),addr)
 thread=threading.Thread(target=serve,daemon=True);thread.start();checks=[]
 opener=build_opener(ProxyHandler({}));process=None
 with tempfile.TemporaryDirectory(prefix='reconnect-test-',dir=TEMP) as d:
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  url=f'http://127.0.0.1:{port}';token=''
  def call(path,body=None):
   headers={'x-control-token':token,'content-type':'application/json'}
   with opener.open(Request(url+path,data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=10) as r:return json.load(r)
  state=lambda:call('/control/state')
  cmd=lambda op,data={}:call('/control/command',{'op':op,'data':data})
  def disconnect(seq):peer.sendto(packet(4,seq,b'\1'),client)
  log_dir=Path(d)/'logs';log_dir.mkdir()
  previous=json.dumps({'message':'previous-session','padding':'x'*(2*1024*1024)})+'\n'
  (log_dir/'runtime.log').write_text(previous,encoding='utf-8')
  try:
   process=subprocess.Popen([os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--config',str(Path(d)/'settings.json'),'--port',str(port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
   token=wait(lambda:state()['token']);cmd('reconnect_settings',{'enabled':True,'window_seconds':4,'interval_seconds':1});cmd('connect',{'target':'127.0.0.1:'+str(peer.getsockname()[1])});assert state()['device']['connected']
   before=opens;disconnect(30);wait(lambda:state()['device']['reconnect_until']);wait(lambda:state()['device']['connected']);assert opens>before;assert state()['device']['reconnect_until'] is None
   checks.append('unexpected_disconnect_reconnects_through_real_sdk')
   answer=False;disconnect(31);wait(lambda:state()['device']['reconnect_until']);wait(lambda:not state()['device']['reconnect_until'],7);assert not state()['device']['connected'];assert not state()['device']['connecting'];before=opens;time.sleep(1.3);assert opens==before
   checks.append('retry_window_stops_pending_open_and_future_attempts')
   answer=True;cmd('connect',{'target':'127.0.0.1:'+str(peer.getsockname()[1])});answer=False;disconnect(32);wait(lambda:state()['device']['reconnect_until']);cmd('disconnect');assert state()['device']['reconnect_until'] is None;before=opens;time.sleep(1.3);assert opens==before
   checks.append('manual_disconnect_cancels_scheduled_reconnect')
   cmd('stop');process.wait(10)
   records=[json.loads(line) for line in (Path(d)/'logs/runtime.log').read_text(encoding='utf-8').splitlines()]
   messages=[r['message'] for r in records]
   assert any('设备已断开：DeviceExit' in m and 'sending=' in m for m in messages)
   assert any('自动重连' in m for m in messages)
   assert any('用户主动断开' in m for m in messages)
   assert all(r['unix_ms']>0 for r in records)
   assert (log_dir/'runtime.previous.log').read_text(encoding='utf-8')==previous
   checks.append('connection_diagnostics_survive_process_exit')
   checks.append('runtime_log_rotates_and_preserves_previous_session')
  finally:
   if process and process.poll() is None:process.terminate();process.wait(5)
   running=False;thread.join(2);peer.close()
 result={'passed':len(checks),'checks':checks,'physical_device_tested':False};(RESULTS/'reconnect-integration-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
