import io,json,subprocess,sys,tempfile,unittest,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'python/plugin_kit'))
from screen_plugin import Context

def wav(rate=16000,channels=1,width=2,frames=160):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(channels);w.setsampwidth(width);w.setframerate(rate);w.writeframes(bytes(frames*channels*width))
    return out.getvalue()

class AudioTests(unittest.TestCase):
    def test_bytes_or_path_single_file_and_volume(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d);ctx=Context({'settings':{},'state':{}},root,root/'data',root/'frame.png')
            ctx.play_wav(wav(),33)
            self.assertEqual(ctx._audio,{'path':'frame.wav','volume':33})
            self.assertEqual((root/'frame.wav').read_bytes(),wav())
            with self.assertRaises(ValueError):ctx.play_wav(wav())
            ctx=Context({'settings':{},'state':{}},root,root/'data',root/'frame.png')
            ctx.play_wav(root/'frame.wav')
            self.assertEqual(ctx._audio['volume'],90)
    def test_bad_format_duration_size_volume(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d)
            for raw,volume in [(wav(rate=8000),90),(wav(channels=2),90),(wav(width=1),90),(wav(frames=48001),90),(b'x'*98305,90),(wav(frames=0),90),(wav(),101),(wav(),True),(wav(),1.5),(wav()[:-1],90)]:
                ctx=Context({'settings':{},'state':{}},root,root/'data',root/'frame.png')
                with self.subTest(length=len(raw),volume=volume),self.assertRaises((ValueError,wave.Error,EOFError)):ctx.play_wav(raw,volume)
    def test_real_worker_audio_only_and_with_image(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d);(root/'sound.wav').write_bytes(wav())
            for show in (False,True):
                (root/'main.py').write_text("def handle(ctx,event):\n ctx.play_wav(ctx.package_dir/'sound.wav',42)\n"+(" ctx.show(ctx.canvas())\n" if show else ''),encoding='utf-8')
                request={'entry':'main.py','event':{'type':'manual'},'settings':{},'state':{}}
                result=subprocess.run([sys.executable,str(ROOT/'python/plugin_worker.py'),str(root),str(root/'frame.png'),str(root/'data')],input=json.dumps(request),text=True,capture_output=True,check=True)
                value=json.loads(result.stdout);self.assertEqual(value['shown'],show);self.assertEqual(value['audio'],{'path':'frame.wav','volume':42})
if __name__=='__main__':unittest.main()
