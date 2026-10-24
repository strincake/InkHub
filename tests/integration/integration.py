"""Exercise the real binary and SDK against a loopback-only Note4 protocol peer."""
import ast
import io
import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
# Reuse the existing independently exercised protocol simulator, without executing its tests.
tree=ast.parse((ROOT/'tests/support/note4_peer.py').read_text(encoding='utf-8'))
peer_node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Peer')
exec(compile(ast.Module(body=[peer_node],type_ignores=[]),'existing-peer','exec'))
def wait(fn,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError,KeyError):pass
        time.sleep(.08)
    raise AssertionError('condition timed out')

def main():
    opener=build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(dir=TEMP,prefix='integration-') as directory:
        tmp=Path(directory); config=tmp/'settings.json';pool=tmp/'photos';pool.mkdir()
        Image.new('RGB',(800,600),'#dbb58f').save(pool/'01.jpg')
        Image.new('RGB',(300,500),'#698665').save(pool/'02.png')
        Image.new('RGB',(400,300),'#a5b7c2').save(pool/'03.png')
        peer=Peer();process=None
        env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        cmd=[os.environ.get('SCHEDULER_BINARY',str(ROOT/'target/debug/note4-screen-scheduler.exe')),'--port',str(port),'--config',str(config),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0']
        def call(path,body=None,authorized=True,raw=False):
            headers={}
            if body is not None:
                if not isinstance(body,bytes):body=json.dumps(body).encode();headers['Content-Type']='application/json'
                if authorized:headers['x-control-token']=token
            try:
                with opener.open(Request(base+path,data=body,headers=headers),timeout=25) as r:
                    content=r.read();return r.status,content if raw else json.loads(content)
            except HTTPError as e:return e.code,e.read()
        def state():return call('/control/state')[1]
        def command(op,id='',data=None):
            result=call('/control/command',{'op':op,'id':id,'data':data or {}})
            assert result[0]==200,result
            return result[1]
        checks=[]
        try:
            process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
            token=wait(lambda:state()['token']);checks.append('service_start')
            assert call('/control/command',{'op':'add'},authorized=False)[0]==403
            checks.append('mutation_requires_session_token')
            a=command('add',data={'name':'状态测试','min_ms':0,'hold_ms':0,'ttl_ms':0})['id']
            img=io.BytesIO();Image.new('RGB',(400,300),'white').save(img,format='PNG')
            assert call('/control/image/'+a,img.getvalue())[0]==200
            wait(lambda:state()['current'] and state()['current']['frame']['id']==a)
            assert '模拟' in state()['device']['health'];checks.append('simulation_display_receipt')
            command('key',data={'key':'Confirm'})
            assert state()['sources'][0]['keys'][-1]['key']=='Confirm';checks.append('key_routes_to_displayed_source')
            before=state()['sources'][0]['config']
            command('settings',a,{'name':'改名不重发','priority':2})
            after=state()['sources'][0]['config']
            assert before['revision']==after['revision'] and before['updated_at']==after['updated_at']
            checks.append('metadata_edits_do_not_republish_or_renew_task')
            def plugin():return next(p for p in state()['plugins'] if p['id']=='local-gallery')
            def plugin_command(op,data=None):
                result=call('/control/plugins/local-gallery',{'op':op,'data':data or {}});assert result[0]==200,result
            archive=(ROOT/'dist/plugins/local-gallery.screen-plugin.zip').read_bytes()
            assert call('/control/plugins/install',archive)[0]==200
            gallery_settings={'sources':[{'id':'regression-album','name':'插件相册','folder':str(pool),'mode':'固定一张','order':'顺序','interval_seconds':30,'fixed_image':'02.png','fit':'contain'}]}
            def album_state():return plugin()['state'].get('albums',{}).get('regression-album',{})
            plugin_command('settings',gallery_settings)
            plugin_command('enable');wait(lambda:album_state().get('total')==3)
            p=plugin()['channels']['regression-album'];command('settings',p,{'name':'插件相册','priority':4})
            edited=next(s for s in state()['sources'] if s['config']['id']==p)
            assert edited['config']['name']=='插件相册' and edited['config']['priority']==4
            checks.append('gallery_plugin_uses_standard_source_display_rules')
            command('remove',a);wait(lambda:state()['current'] and state()['current']['frame']['id']==p)
            with opener.open(base+'/control/image/'+p) as response:
                assert Image.open(io.BytesIO(response.read())).getpixel((0,0))[:3]==(255,255,255)
            gallery_settings['sources'][0]['fit']='cover'
            plugin_command('settings',gallery_settings)
            wait(lambda:not plugin()['running'] and not plugin()['pending'])
            def covered():
                with opener.open(base+'/control/image/'+p) as response:return Image.open(io.BytesIO(response.read())).getpixel((0,0))[:3]!=(255,255,255)
            wait(covered)
            with opener.open(base+'/control/image/'+p) as response:
                assert Image.open(io.BytesIO(response.read())).getpixel((0,0))[:3]!=(255,255,255)
            checks.append('fixed_pool_rerenders_on_fit_change')
            def settled():
                current=state();pool_source=next(s for s in current['sources'] if s['config']['id']==p)
                return not current['device']['sending'] and current['current']['frame']['revision']==pool_source['config']['revision']
            wait(settled)
            command('key',data={'key':'Down'});wait(lambda:album_state().get('current')=='03.png')
            wait(settled)
            checks.append('ordinary_jpeg_pool_and_manual_next')
            # Real SDK transport, but strictly to a local protocol simulator.
            command('mode',data={'mode':'device'});peer.delay_until=time.monotonic()+2
            command('connect',data={'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['device']['sending']);assert state()['current'] is None
            wait(lambda:state()['current'] and not state()['device']['sending'])
            assert '设备已报告' in state()['device']['health'];checks.append('sdk_waits_for_device_display_completion')
            prior=album_state()['current'];peer.key(2,999)
            wait(lambda:album_state()['current']!=prior)
            wait(lambda:not state()['device']['sending']);checks.append('physical_protocol_key_to_pool_next')
            command('disconnect');assert peer.closes>0;checks.append('sdk_explicit_close')
            # Unknown result must stop automatic sends, including future source updates.
            peer.unknown=True;command('connect',data={'target':f'127.0.0.1:{peer.address[1]}'})
            wait(lambda:state()['device']['blocked']);begins=peer.begins
            key_count=len(next(s for s in state()['sources'] if s['config']['id']==p)['keys'] or [])
            command('key',data={'key':'Confirm'})
            assert len(next(s for s in state()['sources'] if s['config']['id']==p)['keys'] or [])==key_count
            time.sleep(1.5);assert peer.begins==begins;checks.append('unknown_result_blocks_automatic_resend')
            checks.append('unknown_display_result_suppresses_key_forwarding')
            command('disconnect')
            a=command('add',data={'name':'不持久化的来源'})['id']
            process.terminate();process.wait(5)
            process=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
            token=wait(lambda:state()['token'])
            assert all(s['config']['id']!=a for s in state()['sources'])
            assert plugin()['enabled']
            assert not state()['device']['connected'];checks.append('restart_restores_gallery_plugin_not_external_tasks_or_connection')
            print(json.dumps({'passed':len(checks),'checks':checks,'physical_device_tested':False},ensure_ascii=False,indent=2))
            (RESULTS/'integration-result.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'physical_device_tested':False},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            if process and process.poll() is None:process.terminate();process.wait(5)
            peer.running=False;peer.socket.close()
if __name__=='__main__':main()
