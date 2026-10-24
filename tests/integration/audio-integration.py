"""Temporary host + loopback NOTE4 peer. Never uses saved config or physical hardware."""
import ast,io,json,os,socket,struct,subprocess,sys,tempfile,threading,time,zipfile
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'tests/unit'))
from test_plugin_audio import wav
from PIL import Image
from integration import wait
peer_source=(ROOT/'tests/support/note4_peer.py').read_text(encoding='utf-8')
peer_tree=ast.parse(peer_source)
peer_code=ast.get_source_segment(peer_source,next(n for n in peer_tree.body if isinstance(n,ast.ClassDef) and n.name=='Peer'))
peer_code=peer_code.replace('self.image=0;self.bitmap=0;self.playback=0;', 'self.stops=0;self.audio_unknown=False;self.audio_reason=0;self.image=0;self.bitmap=0;self.playback=0;')
peer_code=peer_code.replace("self.socket.sendto(self.packet(13,100+seq,", "if self.audio_unknown:continue\n                self.socket.sendto(self.packet(13,100+seq,")
peer_code=peer_code.replace('elif kind in (10,11):','elif kind in (10,11):\n                if kind==11:self.stops+=1')
peer_code=peer_code.replace('bytes([2,0])','bytes([2,self.audio_reason])')
exec(compile(peer_code,'audio-test-peer','exec'))

def main():
    binary=Path(os.environ.get('SCREEN_SCHEDULER_TEST_BINARY',os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe'))))
    opener=build_opener(ProxyHandler({}));peer=Peer();process=None;checks=[]
    with tempfile.TemporaryDirectory(dir=TEMP,prefix='audio-integration-') as directory:
        tmp=Path(directory)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        def call(path,body=None):
            headers={}
            if body is not None:
                if not isinstance(body,bytes):body=json.dumps(body).encode();headers['Content-Type']='application/json'
                headers['x-control-token']=token
            with opener.open(Request(base+path,data=body,headers=headers),timeout=30) as response:return json.loads(response.read())
        state=lambda:call('/control/state')
        command=lambda op,data={}:call('/control/command',{'op':op,'data':data})
        plugin=lambda:next(p for p in state()['plugins'] if p['id']=='audio-check')
        control=lambda op,data={}:call('/control/plugins/audio-check',{'op':op,'data':data})
        def settled():
            s=state();p=plugin();return not p['running'] and not p['pending'] and not s['device']['sending']
        try:
            process=subprocess.Popen([str(binary),'--port',str(port),'--config',str(tmp/'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            token=wait(lambda:state()['token'])
            archive=io.BytesIO()
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('plugin.json',json.dumps({'api_version':1,'id':'audio-check','name':'audio-check','version':'1','entry':'main.py','source_defaults':{'ttl_ms':0,'hold_ms':0,'persistent':True},'triggers':{'startup':True,'actions':[{'id':'sound','label':'sound'},{'id':'new-frame','label':'new frame'},{'id':'slow-sound','label':'slow sound'}]}}))
                z.writestr('sound.wav',wav(frames=1600))
                z.writestr('main.py',"import time\ndef handle(ctx,event):\n if event.get('action')=='slow-sound':time.sleep(1)\n if event['type']=='startup' or event.get('action')=='new-frame':ctx.show(ctx.canvas())\n ctx.play_wav(ctx.package_dir/'sound.wav',25)\n")
            call('/control/plugins/install',archive.getvalue());control('enable')
            wait(lambda:state()['device']['audio']['status']=='simulated')
            assert peer.audio==0;assert state()['current']['frame']['revision']==state()['device']['audio']['revision'];checks.append('simulation_audio_separate_from_sdk_receipt')
            wait(settled);command('mode',{'mode':'device'});peer.delay_until=time.monotonic()+2
            command('connect',{'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:peer.begins>0);assert peer.audio==0
            wait(lambda:state()['current'] and not state()['device']['sending'])
            peer.delay_until=time.monotonic()+1.2
            control('run',{'action':'new-frame'})
            wait(lambda:state()['device']['sending']);assert peer.audio==0
            wait(lambda:state()['device']['audio']['status']=='playback_ended')
            assert peer.audio==1;assert state()['device']['audio']['reason']=='Completed';checks.append('attached_sound_after_display_completion_sdk_playback_receipt')
            before=state()['current']['frame']['revision'];control('run',{'action':'sound'})
            wait(lambda:peer.audio==2);wait(settled);assert state()['current']['frame']['revision']==before;checks.append('audio_only_manual_uses_current_revision')
            control('run',{'action':'slow-sound'});wait(lambda:plugin()['running'])
            other=command('add',{'name':'other','priority':1,'bypass':True,'min_ms':0,'hold_ms':0,'ttl_ms':0})['id']
            picture=io.BytesIO();Image.new('RGB',(400,300),'black').save(picture,format='PNG');call('/control/image/'+other,picture.getvalue())
            wait(lambda:state()['current']['frame']['id']==other);wait(settled);assert peer.audio==2
            call('/control/command',{'op':'remove','id':other});wait(lambda:state()['current'] and state()['current']['frame']['id']==plugin()['source']);wait(settled);assert peer.audio==2
            checks.append('late_audio_only_discarded_after_source_switch_and_not_replayed_on_return')
            count=peer.audio
            control('run',{'action':'slow-sound'});wait(lambda:plugin()['running'])
            command('global',{'paused':True});wait(lambda:not plugin()['running'] and not plugin()['pending'])
            command('global',{'paused':False});time.sleep(.5);assert peer.audio==count
            checks.append('pause_during_slow_sound_drops_cue_after_resume')
            control('run',{'action':'slow-sound'});wait(lambda:plugin()['running'])
            command('global',{'paused':True});command('global',{'paused':False})
            wait(settled);time.sleep(.4);assert peer.audio==count
            checks.append('pause_and_resume_before_worker_return_invalidates_old_media_epoch')
            control('run',{'action':'sound'});wait(lambda:peer.audio==count+1);wait(settled)
            checks.append('new_manual_sound_after_resume_still_plays')
            peer.audio_unknown=True;control('run',{'action':'sound'});wait(lambda:peer.audio==count+2 and state()['device']['sending'])
            peer.socket.sendto(peer.packet(8,881,b'\0'),peer.client);wait(lambda:state()['device']['recording'])
            wait(lambda:state()['device']['audio'].get('reason')=='Interrupted');peer.audio_unknown=False
            assert peer.stops==0;baseline_audio=peer.audio;checks.append('recording_interrupts_playback_without_stopping_user_capture')
            count=peer.begins;control('run',{'action':'new-frame'});wait(lambda:not plugin()['running'] and not plugin()['pending']);time.sleep(.4)
            assert peer.begins==count and peer.audio==baseline_audio
            peer.socket.sendto(peer.packet(10,882,struct.pack('>IIHB',881,0,0,0)),peer.client)
            wait(lambda:not state()['device']['recording']);wait(lambda:peer.begins>count);wait(settled);assert peer.audio==baseline_audio;checks.append('recording_pauses_frames_discards_sounds_and_resumes_without_saved_audio')
            command('disconnect');peer.unknown=True;command('connect',{'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['device']['blocked']);count=peer.begins;control('run',{'action':'new-frame'});wait(lambda:not plugin()['running'] and not plugin()['pending']);time.sleep(.7)
            assert peer.begins==count and peer.audio==baseline_audio;checks.append('unknown_display_blocks_all_media_without_retry')
            command('reconnect_settings',{'enabled':True,'window_seconds':5,'interval_seconds':1})
            peer.socket.sendto(peer.packet(4,883,b'\1'),peer.client)
            wait(lambda:state()['device']['reconnect_until'])
            wait(lambda:state()['device']['connected'] and not state()['device']['reconnect_until'])
            time.sleep(.4);assert state()['device']['blocked'] and peer.begins==count
            checks.append('automatic_reconnect_preserves_unknown_result_block_without_replay')
            command('reconnect_settings',{'enabled':False,'window_seconds':5,'interval_seconds':1})
            command('disconnect');peer.unknown=False;peer.audio_unknown=True
            command('connect',{'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['current'] and not state()['device']['sending'])
            control('run',{'action':'sound'});wait(lambda:state()['device']['blocked'],seconds=25)
            assert state()['device']['audio']['status']=='result_unknown'
            count=peer.begins;audio_count=peer.audio;control('run',{'action':'new-frame'});wait(lambda:not plugin()['running'] and not plugin()['pending']);time.sleep(.5)
            assert peer.begins==count and peer.audio==audio_count;checks.append('unknown_playback_blocks_images_and_sounds_without_retry')
            command('disconnect');peer.audio_unknown=False;peer.audio_reason=1
            command('connect',{'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['current'] and not state()['device']['sending'])
            control('run',{'action':'sound'});wait(lambda:state()['device']['blocked'])
            assert state()['device']['audio']['status']=='failed';checks.append('failed_playback_blocks_all_media')
            control('disable');command('disconnect');command('mode',{'mode':'simulation'});time.sleep(.4)
            assert state()['device']['audio']['status']!='playing';checks.append('disable_clears_pending_sound')
            command('stop');process.wait(timeout=10)
            print(json.dumps({'passed':len(checks),'checks':checks,'physical_device_tested':False},ensure_ascii=False,indent=2))
        finally:
            if process and process.poll() is None:process.kill();process.wait()
            if process and process.stderr:
                error=process.stderr.read().decode('utf-8','replace')
                if error:print(error,file=sys.stderr)
            peer.running=False;peer.socket.close()
if __name__=='__main__':main()
