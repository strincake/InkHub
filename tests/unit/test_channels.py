import sys,tempfile,unittest
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'python/plugin_kit'))
from screen_plugin import Context
class ChannelTests(unittest.TestCase):
 def test_exact_dimensions(self):
  with tempfile.TemporaryDirectory(dir=TEMP) as d:
   c=Context({'settings':{},'state':{}},d,d,Path(d)/'frame.png')
   with self.assertRaises(ValueError):c.show(Image.new('RGB',(100,100)))
 def test_independent_channels(self):
  with tempfile.TemporaryDirectory(dir=TEMP) as d:
   c=Context({'settings':{},'state':{},'channels':{'one':{'visible':True}}},d,d,Path(d)/'frame.png')
   a=c.register_channel('one','相册一');b=c.register_channel('two','相册二')
   a.show(a.canvas('red'));b.show(b.canvas('blue'))
   self.assertTrue(a.display['visible']);self.assertFalse(b.display['visible'])
   self.assertEqual(len(c._channels),2)
   self.assertNotEqual(a._output,b._output)
if __name__=='__main__':unittest.main()

