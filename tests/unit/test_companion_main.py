"""Exercise plugin event/state boundaries without a real Codex account or device."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
PACKAGE = ROOT / 'plugins' / 'codex-companion'
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(ROOT / 'python' / 'plugin_kit'))
from screen_plugin import Context
from companion_core import DEFAULT_SETTINGS, Model


class EventContext:
    font = Context.font

    def __init__(self, folder, state=None, **settings):
        self.settings = dict(DEFAULT_SETTINGS, **settings)
        self.settings['sessions_path'] = str(folder / 'sessions')
        (folder / 'sessions').mkdir(exist_ok=True)
        self.state = {} if state is None else state
        self.package_dir = PACKAGE
        self.data_dir = folder
        self.display = dict(visible=True, now=10000, shown_at=6000, revision=1, format='mono')
        self.images, self.clips = [], []

    def show(self, image, format='mono'):
        self.images.append(image)

    def play_wav(self, data, volume=90):
        self.clips.append((data, volume))

    def trigger_after(self, seconds):
        self.after = seconds

    def require_visible(self):
        self.requires_visible = True


def task(seq=1, status='working', identity='a'):
    return dict(task_id=identity, seq=seq, title='测试任务', status=status, agent='测试')


class MainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('companion_entry', PACKAGE / 'main.py')
        cls.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.entry)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='companion-main-', dir=TEMP)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_idle_does_not_keep_republishing_the_same_picture(self):
        ctx = EventContext(self.folder, animation=False)
        self.entry.handle(ctx, {'type': 'startup'})
        self.assertEqual(len(ctx.images), 1)
        ctx.images.clear()
        self.entry.handle(ctx, {'type': 'interval'})
        self.assertEqual(ctx.images, [])
        self.assertGreaterEqual(ctx.after, 3)

    def test_historical_done_on_startup_never_plays_and_fresh_transition_plays_once(self):
        ctx = EventContext(self.folder, sound_enabled=True, animation=False)
        now = time.time()
        Model(ctx.state, ctx.settings, now).apply(task(status='done'), 'codex', now)
        self.entry.handle(ctx, {'type': 'startup'})
        self.assertEqual(ctx.clips, [])
        Model(ctx.state, ctx.settings, now).apply(task(identity='b'), 'agent', now)
        with patch.object(self.entry, 'ingest_inbox', side_effect=lambda folder, model, now: model.apply(task(2, 'waiting', 'b'), 'agent', now)):
            self.entry.handle(ctx, {'type': 'interval'})
        self.assertEqual(len(ctx.clips), 1)
        self.entry.handle(ctx, {'type': 'interval'})
        self.assertEqual(len(ctx.clips), 1)

    def test_animation_only_advances_while_visible_and_after_2500ms(self):
        ctx = EventContext(self.folder)
        Model(ctx.state, ctx.settings, time.time()).apply(task(), 'agent')
        self.entry.handle(ctx, {'type': 'startup'})
        first = ctx.state.get('_phase', 0)
        ctx.display['visible'] = False
        self.entry.handle(ctx, {'type': 'interval'})
        self.assertEqual(ctx.state.get('_phase', 0), first)
        ctx.display.update(visible=True, now=7000)
        self.entry.handle(ctx, {'type': 'interval'})
        self.assertEqual(ctx.state.get('_phase', 0), first)
        ctx.display['now'] = 10000
        self.entry.handle(ctx, {'type': 'interval'})
        self.assertNotEqual(ctx.state.get('_phase', 0), first)
        self.assertTrue(ctx.requires_visible)

    def test_changing_session_folder_clears_old_codex_approvals(self):
        ctx = EventContext(self.folder, animation=False)
        self.entry.handle(ctx, {'type': 'startup'})
        ctx.state['selected'] = 'codex:old-turn'
        ctx.state['approvals']['requests'] = [dict(thread_id='old-chat', turn_id='old-turn',
                                                  request_id='old-request', title='旧目录任务',
                                                  tool_name='Bash', at=time.time(), resolved=False)]
        different = self.folder / 'other-sessions'
        different.mkdir()
        ctx.settings['sessions_path'] = str(different)
        self.entry.handle(ctx, {'type': 'settings_changed'})
        self.assertEqual(ctx.state['approvals']['requests'], [])
        self.assertIsNone(ctx.state['selected'])

    def test_demo_is_labeled_and_key_restores_real_tasks(self):
        ctx = EventContext(self.folder, animation=False)
        self.entry.handle(ctx, {'type': 'manual', 'action': 'demo-working'})
        self.assertEqual(ctx.state['_demo'], 'working')
        self.entry.handle(ctx, {'type': 'key', 'key': 'Confirm'})
        self.assertIsNone(ctx.state['_demo'])
        self.assertIsNone(ctx.state['selected'])

    def test_displayed_event_does_not_create_refresh_loop(self):
        ctx = EventContext(self.folder)
        self.entry.handle(ctx, {'type': 'displayed', 'revision': 2})
        self.assertEqual(ctx.images, [])
        self.assertEqual(ctx.clips, [])


if __name__ == '__main__':
    unittest.main()
