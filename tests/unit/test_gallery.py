import importlib.util,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageFont
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('gallery',ROOT/'plugins/local-gallery/main.py')
gallery=importlib.util.module_from_spec(spec);spec.loader.exec_module(gallery)
class Context:
    def __init__(self,folder):
        self.settings={'folder':str(folder),'mode':'轮播','order':'顺序','interval_seconds':30,'fixed_image':''}
        self.state={};self.display={'visible':True,'fit':'contain','format':'mono'};self.shown=None;self.after=None
    def show(self,image,format='mono'):self.shown=image.copy();self.format=format
    def trigger_after(self,n):self.after=n
    def require_visible(self):pass
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TEMP);self.folder=Path(self.tmp.name)
        for n,color in enumerate(['red','green','blue']):Image.new('RGB',(100,200),color).save(self.folder/f'{n}.png')
        self.ctx=Context(self.folder)
    def tearDown(self):self.tmp.cleanup()
    def event(self,event):self.ctx.shown=None;self.ctx.after=None;gallery.handle(self.ctx,event)
    def test_start_preserves_migrated_selected_image(self):
        self.ctx.state['current']='1.png';self.event({'type':'startup'});self.assertEqual(self.ctx.state['current'],'1.png');self.assertIsNotNone(self.ctx.shown)
    def test_timer_starts_after_actual_display(self):
        self.event({'type':'startup'});self.assertIsNone(self.ctx.after)
        self.event({'type':'displayed'});self.assertEqual(self.ctx.after,30);self.assertIsNone(self.ctx.shown)
    def test_hidden_interval_pauses_without_publishing(self):
        self.event({'type':'startup'});self.ctx.display['visible']=False;old=self.ctx.state['current'];self.event({'type':'interval'});self.assertEqual(self.ctx.state['current'],old);self.assertIsNone(self.ctx.shown);self.assertIsNone(self.ctx.after)
    def test_fixed_image_and_manual_previous_next(self):
        self.ctx.settings.update(mode='固定一张',fixed_image='1.png');self.event({'type':'startup'});self.assertEqual(self.ctx.state['current'],'1.png');self.event({'type':'key','key':'Down'});self.assertEqual(self.ctx.state['current'],'2.png');self.event({'type':'key','key':'Up'});self.assertEqual(self.ctx.state['current'],'1.png');self.event({'type':'displayed'});self.assertIsNone(self.ctx.after);self.event({'type':'interval'});self.assertIsNone(self.ctx.shown);self.assertEqual(self.ctx.state['current'],'1.png')
    def test_random_rounds_and_history(self):
        self.ctx.settings['order']='随机';self.event({'type':'startup'});seen=[self.ctx.state['current']]
        for _ in range(2):self.event({'type':'key','key':'Down'});seen.append(self.ctx.state['current'])
        self.assertEqual(len(set(seen)),3);self.event({'type':'key','key':'Up'});self.assertEqual(self.ctx.state['current'],seen[-2])
    def test_contain_cover_and_grayscale_choice(self):
        self.event({'type':'startup'});self.assertEqual(self.ctx.shown.getpixel((0,0)),(255,255,255));self.ctx.settings['fit']='cover';self.ctx.display.update(format='gray16');self.event({'type':'manual','action':'refresh'});self.assertNotEqual(self.ctx.shown.getpixel((0,0)),(255,255,255));self.assertEqual(self.ctx.format,'gray16')
    def test_corrupt_picture_is_skipped(self):
        (self.folder/'-bad.png').write_bytes(b'broken');self.event({'type':'startup'});self.assertNotEqual(self.ctx.state['current'],'-bad.png');self.assertIsNotNone(self.ctx.shown)
    def test_rescan_after_removal(self):
        self.event({'type':'startup'});(self.folder/self.ctx.state['current']).unlink();self.event({'type':'manual','action':'rescan'});self.assertTrue((self.folder/self.ctx.state['current']).exists())
if __name__=='__main__':unittest.main()
