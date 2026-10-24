import json,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'python'))
from migrate_gallery import migrate
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
TEMPLATE=ROOT/'plugins/local-gallery'
def pool(id,name,enabled=True):
    return [{'id':id,'name':name,'priority':2,'min_ms':7000,'hold_ms':0,'ttl_ms':0,'persistent':True,'bypass':True,'enabled':enabled,'format':'gray16','fit':'cover','revision':3,'updated_at':99,'order':2,'consumed':2,'boost':None}, {'folder':'C:/Pictures','fixed':True,'shuffle':True,'interval_ms':12500,'selected':'C:/Pictures/selected.png','files':['C:/Pictures/selected.png'],'index':0}]
class Tests(unittest.TestCase):
    def test_preserves_multiple_pools_and_general_settings(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            config=Path(d)/'settings.json';original={'target':'127.0.0.1','preempt':False,'api_key':'test-key','pools':[pool('one','相册一'),pool('two','相册二',False)]};config.write_text(json.dumps(original),encoding='utf-8')
            result=migrate(config,TEMPLATE);self.assertEqual(result['migrated'],2)
            updated=json.loads(config.read_text(encoding='utf-8'));self.assertNotIn('pools',updated);self.assertEqual(updated['api_key'],'test-key');self.assertFalse(updated['preempt'])
            records=[json.loads(p.read_text(encoding='utf-8')) for p in config.with_suffix('.plugins').glob('data/*/record.json')]
            self.assertEqual({r['source']['name'] for r in records},{'相册一','相册二'})
            for r in records:
                self.assertEqual(r['settings']['folder'],'C:/Pictures');self.assertEqual(r['settings']['fixed_image'],'selected.png');self.assertEqual(r['settings']['interval_seconds'],12.5);self.assertEqual(r['source']['format'],'gray16');self.assertEqual(r['source']['fit'],'cover');self.assertEqual(r['source']['priority'],2)
            self.assertEqual({r['enabled'] for r in records},{True,False});self.assertEqual(json.loads(config.with_name(result['backup']).read_text(encoding='utf-8')),original)
            self.assertEqual(migrate(config,TEMPLATE)['migrated'],0)
    def test_retry_after_partial_install_does_not_duplicate_or_reset(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            config=Path(d)/'settings.json';original={'pools':[pool('one','一')]};config.write_text(json.dumps(original),encoding='utf-8')
            result=migrate(config,TEMPLATE);record=config.with_suffix('.plugins')/'data'/result['plugins'][0]/'record.json'
            saved=json.loads(record.read_text(encoding='utf-8'));saved['settings']['interval_seconds']=42;record.write_text(json.dumps(saved),encoding='utf-8')
            config.write_text(json.dumps(original),encoding='utf-8');migrate(config,TEMPLATE)
            self.assertEqual(json.loads(record.read_text(encoding='utf-8'))['settings']['interval_seconds'],42)
            self.assertEqual(len(list(config.with_suffix('.plugins').glob('packages/*'))),1)
if __name__=='__main__':unittest.main()
