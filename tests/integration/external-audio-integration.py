"""External audio acceptance, deduplication and lifecycle against an isolated host."""
import io,json,os,sys,socket,struct,subprocess,tempfile,time,zlib
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from PIL import Image
from integration import wait,Peer


ROOT=Path(__file__).resolve().parents[2]
TEMP=ROOT/'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS=ROOT/'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tests/unit'))
from test_plugin_audio import wav
sys.path.insert(0,str(ROOT/'clients/screen-scheduler-client/python'))
from screen_scheduler import Device,OpenOptions
def main():
    opener=build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(dir=TEMP,prefix='external-audio-') as directory:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        process=subprocess.Popen([os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--port',str(port),'--config',str(Path(directory)/'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def request(url,method='GET',data=None,headers=None):
            with opener.open(Request(url,data=data,method=method,headers=headers or {}),timeout=10) as r:return json.load(r)
        state=lambda:request(base+'/control/state')
        try:
            initial=wait(state);token=initial['token'];access=initial['access']
            def command(op,data=None):return request(base+'/control/command','POST',json.dumps({'op':op,'data':data or {}}).encode(),{'x-control-token':token,'Content-Type':'application/json'})
            api='http://'+access['http']
            client=Device.open(OpenOptions(api,'external audio'),api_key=access['api_key'])
            session={'id':client.id,'token':client._token}
            headers={'Authorization':'Bearer '+session['token']}
            path=api+'/v1/sessions/'+session['id']+'/frames/1'
            png=io.BytesIO();Image.new('RGB',(400,300),'white').save(png,format='PNG')
            request(path,'POST',png.getvalue(),headers)
            wait(lambda:state()['current'])
            result=client.play_wav(wav(frames=1600),sequence=1)
            assert result['semantics']=='accepted_by_scheduler'
            wait(lambda:state()['device']['audio']['status']=='simulated')
            # A retry after playback must not enqueue again.
            assert request(path+'/audio','POST',wav(frames=1600),headers)==result
            def rejected(url,data,h,code):
                try:request(url,'POST',data,h)
                except HTTPError as e:assert e.code==code,(e.code,e.read());return
                raise AssertionError('request unexpectedly accepted')
            rejected(path+'/audio',wav(frames=1601),headers,409)
            rejected(path+'/audio',b'bad',headers,400)
            rejected(path+'/audio',wav(frames=1),{},401)
            request(path[:-1]+'2','POST',png.getvalue(),headers)
            rejected(path+'/audio',wav(frames=1),headers,409)
            peer=Peer()
            command('mode',{'mode':'device'});command('connect',{'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['current'] and not state()['device']['sending'])
            peer.delay_until=time.monotonic()+1
            third=path[:-1]+'3'
            request(third,'POST',png.getvalue(),headers)
            request(third+'/audio','POST',wav(frames=1600),headers)
            wait(lambda:state()['device']['sending']);assert peer.audio==0
            wait(lambda:state()['device']['audio']['status']=='playback_ended');assert peer.audio==1
            request(third+'/audio','POST',wav(frames=1600),headers);time.sleep(.3);assert peer.audio==1
            fourth=path[:-1]+'4';request(fourth,'POST',png.getvalue(),headers)
            command('global',{'paused':True});rejected(fourth+'/audio',wav(frames=1),headers,409)
            command('global',{'paused':False})
            client.close()
            # Legacy UDP producer, including managed playback result through STATE.
            host,udp_port=access['sdk'].rsplit(':',1)
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.settimeout(3);sock.connect((host,int(udp_port)))
            connection=0
            def packet(kind,seq,body=b''):return b'ZL\1'+bytes([kind])+struct.pack('>QI',connection,seq)+body
            def control(kind,seq,body=b''):
                sock.send(packet(kind,seq,body))
                while True:
                    raw=sock.recv(1200)
                    if raw[3]==kind|128 and struct.unpack('>I',raw[12:16])[0]==seq:return raw
            raw=control(1,1);connection=struct.unpack('>Q',raw[4:12])[0]
            assert control(2,2,b'\x05audio')[16]==0
            compressed=zlib.compress(bytes(15000));assert control(5,3,b'\1'+struct.pack('>H',len(compressed)))[16]==0
            sock.send(packet(6,0,struct.pack('>I',3)+compressed));assert control(7,4,struct.pack('>I',3))[17]==3
            assert control(8,5,b'\x19')[16]==0
            # A valid 60ms mono Opus silence frame.
            sock.send(packet(9,0,struct.pack('>I',5)+bytes.fromhex('5802')))
            end=struct.pack('>IIHB',5,1,960,0)
            assert control(10,6,end)[16]==0
            assert control(10,6,end)[16]==0
            raw=control(12,7);assert struct.unpack('>I',raw[41:45])[0]==5 and raw[45]==0,raw.hex()
            wait(lambda:peer.audio==2);wait(lambda:not state()['device']['sending'])
            assert control(8,8,b'\x65')[16]==2
            assert control(8,9,b'\x19')[16]==0
            sock.send(packet(9,0,struct.pack('>I',9)+bytes.fromhex('5802')))
            command('global',{'paused':True});command('global',{'paused':False})
            assert control(10,10,struct.pack('>IIHB',9,1,960,0))[16]==0
            raw=control(12,11);assert raw[45]==7;time.sleep(.3);assert peer.audio==2
            # Missing packets are rejected without partial playback.
            assert control(8,12,b'\x19')[16]==0
            assert control(10,13,struct.pack('>IIHB',12,1,960,0))[16]==0
            raw=control(12,14);assert raw[45]==7;assert peer.audio==2
            assert control(4,15,b'\0')[16]==0
            sock.close()
            # Real unmodified Rust SDK sends paced Opus, waits for managed STATE, then closes.
            example=ROOT/'target/debug/examples/original_audio.exe'
            if not example.exists():raise AssertionError('build original_audio example first')
            picture=Path(directory)/'frame.png';picture.write_bytes(png.getvalue())
            sdk=subprocess.Popen([str(example),access['sdk'],str(picture)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                wait(lambda:peer.audio==3)
                stdout,stderr=sdk.communicate(timeout=10)
                assert sdk.returncode==0,(stdout,stderr)
                assert b'managed_audio=Completed' in stdout,stdout
            finally:
                if sdk.poll() is None:sdk.terminate();sdk.wait(timeout=5)
            result={'passed':True,'physical_device_tested':False,'checks':['HTTP WAV accepted and simulated','retry does not replay','conflicting, malformed, unauthorized and stale requests rejected','UDP audio accepted, duplicate end idempotent, managed STATE result','invalid volume rejected','HTTP and UDP reach output SDK with playback completion','sound waits for image completion','pause rejects HTTP and invalidates UDP transfer','missing UDP packet rejected without playback','Python play_wav helper','unmodified Rust SDK play completes and reaches output']}
            (RESULTS/'external-audio-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result))
        finally:
            process.terminate();process.wait(timeout=10)
            if 'peer' in locals():peer.running=False;peer.socket.close()

if __name__=='__main__':main()
