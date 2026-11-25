import importlib.util,io,json,tempfile,unittest,zipfile
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('plugin_tools',ROOT/'python/plugin_tools.py')
tools=importlib.util.module_from_spec(spec);spec.loader.exec_module(tools)
def package(manifest=None,extra=None):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('plugin.json',json.dumps(manifest or {'api_version':1,'id':'hello','name':'示例','version':'1.0','entry':'main.py','triggers':{'startup':True}}))
        z.writestr('main.py','def handle(ctx, event): pass')
        for path,content in (extra or {}).items():
            entry=zipfile.ZipInfo();entry.filename=path;z.writestr(entry,content)
    return data.getvalue()
class Tests(unittest.TestCase):
    def test_valid_portable_plugin(self):
        self.assertEqual(tools.inspect_package(package())['id'],'hello')
    def test_corrupt_code_entry_rejected_during_inspection(self):
        data=bytearray(package());offset=data.index(b'def handle');data[offset]=ord('x')
        with self.assertRaises((ValueError,zipfile.BadZipFile)):tools.inspect_package(bytes(data))
    def test_file_directory_conflicts_rejected_during_inspection(self):
        for files in ({'assets':'file','assets/icon.png':'image'},{'Assets':'file','assets/icon.png':'image'}):
            with self.subTest(files=files),self.assertRaises(ValueError):tools.inspect_package(package(extra=files))
    def test_traversal_and_windows_paths_rejected(self):
        for path in ('../evil.py','/evil.py','C:/evil.py','assets/../evil.py','assets\\evil.py','NUL.txt'):
            with self.subTest(path=path),self.assertRaises(ValueError):tools.inspect_package(package(extra={path:'x'}))
    def test_case_insensitive_duplicates_rejected(self):
        with self.assertRaises(ValueError):tools.inspect_package(package(extra={'MAIN.py':'x'}))
    def test_links_rejected(self):
        raw=io.BytesIO(package())
        with zipfile.ZipFile(raw,'a') as z:
            link=zipfile.ZipInfo('link');link.create_system=3;link.external_attr=0o120777<<16;z.writestr(link,'target')
        with self.assertRaises(ValueError):tools.inspect_package(raw.getvalue())
    def test_missing_entry_and_bad_api(self):
        for patch in ({'entry':'missing.py'},{'api_version':2},{'api_version':True},{'id':'../hello'},{'triggers':{'interval_seconds':0}}):
            m={'api_version':1,'id':'hello','name':'测试','version':'1','entry':'main.py'};m.update(patch)
            with self.assertRaises(ValueError):tools.inspect_package(package(m))
    def test_invalid_setting_default(self):
        m={'api_version':1,'id':'hello','name':'测试','version':'1','entry':'main.py','settings':[{'key':'count','label':'数量','type':'number','default':'wrong'}]}
        with self.assertRaises(ValueError):tools.inspect_package(package(m))
    def test_homepage_manifest(self):
        base={'api_version':1,'id':'hello','name':'测试','version':'1','entry':'main.py'}
        for key in ('homepage','settings_page'):
            m={**base,key:'home.html','navigation_title':'我的工作'}
            self.assertEqual(tools.inspect_package(package(m,{'home.html':'<h1>工作</h1>'}))[key],'home.html')
        for patch in ({'homepage':'missing.html'},{'homepage':'../home.html'},{'navigation_title':42},{'navigation_title':''},{'settings':[{'key':'title','label':'标题','type':'text','host_ui':'false'}]}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):tools.inspect_package(package({**base,**patch}))
    def test_hidden_settings_still_validated(self):
        fields=[{'key':'count','label':'数量','type':'number','min':1,'max':9,'default':2,'host_ui':False}]
        self.assertEqual(tools.validate_settings(fields,{'count':3}),{'count':3})
        with self.assertRaises(ValueError):tools.validate_settings(fields,{'count':10})
    def test_install_does_not_overwrite(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            tools.install_package(package(),Path(d))
            with self.assertRaises(ValueError):tools.install_package(package(),Path(d))
    def test_update_replaces_code_and_preserves_private_data(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d);tools.install_package(package(extra={'obsolete.py':'old'}),root)
            private=root/'data/hello/files';private.mkdir(parents=True)
            (private/'note.txt').write_text('private note',encoding='utf-8')
            record=root/'data/hello/record.json';record.write_text('{"state":{"page":2}}')
            m={'api_version':1,'id':'hello','name':'新版','version':'2.0','entry':'main.py'}
            result=tools.install_package(package(m,{'new.py':'new'}),root,update_id='hello')
            self.assertEqual(result['version'],'2.0')
            self.assertFalse((root/'packages/hello/obsolete.py').exists())
            self.assertEqual((root/'packages/hello/new.py').read_text(),'new')
            self.assertEqual(record.read_text(),'{"state":{"page":2}}')
            self.assertEqual((private/'note.txt').read_text(encoding='utf-8'),'private note')
            self.assertEqual([p.name for p in (root/'packages').iterdir()],['hello'])
    def test_update_invalid_package_or_id_keeps_old_package(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d);tools.install_package(package(extra={'old.py':'keep'}),root)
            for data,id in ((b'not a ZIP','hello'),(package(),'other'),(package(),'../hello')):
                with self.subTest(id=id),self.assertRaises((ValueError,zipfile.BadZipFile)):
                    tools.install_package(data,root,update_id=id)
                self.assertEqual((root/'packages/hello/old.py').read_text(),'keep')
    def test_update_swap_failure_restores_old_package(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            root=Path(d);tools.install_package(package(extra={'old.py':'keep'}),root)
            rename=Path.rename
            def fail_new_package(path,target):
                if path.name.startswith('staging-'):raise OSError('simulated replacement failure')
                return rename(path,target)
            with patch.object(Path,'rename',fail_new_package),self.assertRaises(OSError):
                tools.install_package(package(),root,update_id='hello')
            self.assertEqual((root/'packages/hello/old.py').read_text(),'keep')
            self.assertEqual([p.name for p in (root/'packages').iterdir()],['hello'])
    def test_update_requires_existing_package(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as d:
            with self.assertRaises(ValueError):tools.install_package(package(),Path(d),update_id='hello')
    def test_update_merges_declared_settings_and_validates_saved_values(self):
        fields=[{'key':'title','label':'标题','type':'text','default':'default'},
                {'key':'count','label':'数量','type':'number','min':1,'default':2}]
        self.assertEqual(tools.merge_settings(fields,{'title':'private','removed':42}),{'title':'private','count':2})
        with self.assertRaises(ValueError):tools.merge_settings(fields,{'count':0})
    def test_expansion_limits(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('big',b'x'*(9*1024*1024))
        with self.assertRaises(ValueError):tools.inspect_package(raw.getvalue())
if __name__=='__main__':unittest.main()
