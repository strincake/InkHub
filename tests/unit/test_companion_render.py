"""Original companion geometry, status coverage and synthesized cue contract."""
import importlib.util
import io
from pathlib import Path
import sys
import unittest
import wave

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
PACKAGE = ROOT / 'plugins' / 'codex-companion'
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(ROOT / 'python' / 'plugin_kit'))
from screen_plugin import Context


class ModelFixture:
    def __init__(self, status='working', count=1, progress=None, selected=None):
        self.settings = {'animation': True, 'codex_enabled': True}
        self.state = {'selected': selected}
        self.items = [dict(source='agent', stale=False, event=dict(
            task_id=f'task-{i}', title=f'测试任务 {i}', status=status,
            detail='正在处理本机任务', progress=progress, agent='测试')) for i in range(count)]

    def current(self):
        return self.items[0] if self.items else None

    def running(self):
        return self.items if self.items and self.items[0]['event']['status'] in ('working', 'waiting') else []


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import companion_render
        cls.renderer = companion_render

    def ctx(self):
        # Font/canvas functions do not require a real worker output directory.
        return type('Fonts', (), {'font': Context.font})()

    def test_all_states_and_frames_fit_native_canvas(self):
        for state in ('working', 'waiting', 'done', 'error', 'stopped', 'unknown'):
            for frame in range(6):
                layout = self.renderer.layout(ModelFixture(state), frame)
                self.assertFalse(any(e.get('content') == 'AI 工作搭子' for e in layout))
                self.assertFalse(any(e['type'] == 'rect' and e['y'] == 82 and e['w'] == 368 for e in layout))
                image = self.renderer.render(self.ctx(), layout)
                self.assertEqual(image.size, (400, 300))
                self.assertTrue(all(0 <= e['y'] < 300 for e in layout))
                self.assertTrue(any(e['type'] == 'rect' and e['y'] == 271 for e in layout))
                self.assertEqual([e['y'] for e in layout[-2:]], [285, 285])

    def test_four_tasks_on_second_page_are_fixed(self):
        model = ModelFixture(count=9, selected='agent:task-4')
        layout = self.renderer.layout(model, 0)
        titles = [e for e in layout if e.get('content', '').startswith('测试任务')]
        self.assertEqual([e['content'] for e in titles], [f'测试任务 {i}' for i in range(4, 8)])
        self.assertEqual([e['y'] for e in titles], [127, 163, 199, 235])

    def test_working_animation_is_optional_and_unknown_progress_is_not_invented(self):
        model = ModelFixture()
        self.assertNotEqual(self.renderer.layout(model, 0), self.renderer.layout(model, 1))
        self.assertFalse(any('%' in e.get('content', '') for e in self.renderer.layout(model, 0)))
        model.settings['animation'] = False
        self.assertEqual(self.renderer.layout(model, 0), self.renderer.layout(model, 3))

    def test_chimes_match_device_pcm_format(self):
        from chimes import wav_bytes
        for status in ('waiting', 'done'):
            raw = wav_bytes(status)
            with wave.open(io.BytesIO(raw), 'rb') as clip:
                self.assertEqual((clip.getnchannels(), clip.getsampwidth(), clip.getframerate()), (1, 2, 16000))
                self.assertLess(clip.getnframes(), 16000)
        self.assertNotEqual(wav_bytes('waiting'), wav_bytes('done'))


if __name__ == '__main__':
    unittest.main()
