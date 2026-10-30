import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python/plugin_kit'))
from screen_plugin import Context

spec = importlib.util.spec_from_file_location('desk_note', ROOT / 'plugins/desk-note/main.py')
note = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note)


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = json.loads((ROOT / 'plugins/desk-note/plugin.json').read_text(encoding='utf-8'))
        settings = {f['key']: f.get('default') for f in manifest['settings']}
        self.ctx = Context({'settings': settings, 'state': {}}, ROOT / 'plugins/desk-note', self.tmp.name, Path(self.tmp.name) / 'frame.png')

    def tearDown(self):
        self.tmp.cleanup()

    def document(self, *items, active='a'):
        self.ctx.settings.update(document={'version': 2, 'notes': list(items)}, active_note=active)

    def item(self, id='a', text='first\n\nsecond', title='Title', show_title=False, font_size=24):
        return dict(id=id, text=text, title=title, show_title=show_title, font_size=font_size)

    def render(self, type='settings_changed', **event):
        note.handle(self.ctx, {'type': type, **event})
        from PIL import Image
        with Image.open(Path(self.tmp.name) / 'frame.png') as img:
            return img.copy()

    def test_multiline_is_one_note_with_blank_line_preserved(self):
        self.document(self.item())
        image = self.render()
        self.assertEqual(self.ctx.state['current_note'], 'a')
        self.assertIsNotNone(image.crop((22, 22, 378, 48)).getbbox())
        self.assertEqual(image.getpixel((22, 60)), (255, 255, 255))
        self.assertLess(min(image.crop((22, 92, 378, 120)).convert('L').getextrema()), 255)
        self.assertEqual(min(image.crop((22, 57, 378, 90)).convert('L').getextrema()), 255)

    def test_title_toggle_moves_body_and_footer_is_absent(self):
        self.document(self.item(text='Body', show_title=True))
        image = self.render()
        self.assertEqual(image.getpixel((22, 60)), (0, 0, 0))
        self.assertEqual(min(image.crop((0, 250, 400, 300)).convert('L').getextrema()), 255)
        self.document(self.item(text='Body', show_title=False))
        image = self.render()
        self.assertEqual(image.getpixel((22, 60)), (255, 255, 255))
        self.assertLess(min(image.crop((22, 22, 378, 50)).convert('L').getextrema()), 255)

    def test_font_size_changes_rendered_height(self):
        self.document(self.item(text='TEST', font_size=12))
        small = self.render().convert('L').point(lambda p: 255-p).getbbox()
        self.document(self.item(text='TEST', font_size=48))
        large = self.render().convert('L').point(lambda p: 255-p).getbbox()
        self.assertGreater(large[3]-large[1], small[3]-small[1] + 10)

    def test_selection_keys_refresh_delete_and_reapply(self):
        self.document(self.item('a'), self.item('b', text='Second'))
        self.render()
        self.render('key', key='Down')
        self.assertEqual(self.ctx.state['current_note'], 'b')
        self.render('interval')
        self.assertEqual(self.ctx.state['current_note'], 'b')
        self.render()
        self.assertEqual(self.ctx.state['current_note'], 'a')
        self.document(self.item('b'), active='missing')
        self.render()
        self.assertEqual(self.ctx.state['current_note'], 'b')

    def test_legacy_notes_keep_old_separate_cards(self):
        self.ctx.settings.update(notes='  one  \n\n two ', title='Legacy')
        self.ctx.state['index'] = 1
        self.render('startup')
        self.assertEqual(self.ctx.state['index'], 1)
        self.assertEqual(note.read_notes(self.ctx.settings)[1]['text'], 'two')

    def test_empty_document_and_long_lines_render_safely(self):
        self.document()
        image = self.render()
        self.assertEqual(min(image.convert('L').getextrema()), 255)
        self.document(self.item(text=('中英文 ABC\t' * 100) + '\nlast', font_size=64))
        image = self.render()
        self.assertEqual(min(image.crop((0, 278, 400, 300)).convert('L').getextrema()), 255)
        self.assertEqual(min(image.crop((378, 0, 400, 300)).convert('L').getextrema()), 255)


if __name__ == '__main__':
    unittest.main()
