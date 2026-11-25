from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python/plugin_kit'))
from screen_plugin import Context, Image


class Tests(unittest.TestCase):
    def plugin(self, name):
        package = ROOT / 'plugins' / name
        manifest = json.loads((package / 'plugin.json').read_text(encoding='utf-8'))
        settings = {field['key']: field['default'] for field in manifest['settings']}
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        spec = importlib.util.spec_from_file_location(name, package / 'main.py')
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        ctx = Context({'settings': settings, 'state': {}}, package, temp.name, Path(temp.name) / 'frame.png')
        return plugin, ctx

    def test_weather_preserves_forecast_offline_for_same_coordinates_only(self):
        plugin, ctx = self.plugin('desk-weather')
        fixture = {
            'current': {'temperature_2m': 21.1, 'weather_code': 2, 'time': '2026-11-24T10:00'},
            'daily': {'temperature_2m_min': [14], 'temperature_2m_max': [23], 'precipitation_probability_max': [25]},
        }
        with patch.object(ctx, 'fetch_json', return_value=fixture) as fetch:
            plugin.handle(ctx, {'type': 'startup'})
            self.assertIn('timezone=auto', fetch.call_args.args[0])
        self.assertEqual(ctx.state['forecast']['temperature'], 21)
        self.assertFalse(ctx.state['offline'])
        with patch.object(ctx, 'fetch_json', side_effect=OSError):
            plugin.handle(ctx, {'type': 'interval'})
            self.assertTrue(ctx.state['offline'])
            self.assertEqual(ctx.state['forecast']['rain'], 25)
            ctx.settings['latitude'] = 40
            plugin.handle(ctx, {'type': 'settings_changed'})
        self.assertNotIn('forecast', ctx.state)
        with Image.open(ctx._output) as image:
            self.assertEqual(image.size, (400, 300))

    def test_timer_pause_resume_and_completion_after_restart(self):
        plugin, ctx = self.plugin('focus-timer')
        def call(now, event):
            with patch.object(plugin, 'time', return_value=now):
                plugin.handle(ctx, event)
        call(100, {'type': 'manual', 'action': 'start-break'})
        self.assertEqual(ctx.state['timer']['deadline'], 400)
        self.assertEqual(ctx._after, 60)
        call(250, {'type': 'key', 'key': 'Confirm'})
        self.assertEqual(ctx.state['timer']['remaining'], 150)
        call(400, {'type': 'manual', 'action': 'toggle'})
        self.assertEqual(ctx.state['timer']['deadline'], 550)
        ctx.state = json.loads(json.dumps(ctx.state))
        call(555, {'type': 'startup'})
        self.assertEqual(ctx.state['timer']['mode'], 'done')
        call(556, {'type': 'manual', 'action': 'reset'})
        self.assertEqual(ctx.state['timer'], {})

    def test_checklist_pages_and_resets_at_local_day_boundary(self):
        plugin, ctx = self.plugin('today-checklist')
        ctx.settings['items'] = 'one\ntwo\nthree\nfour\nfive\nsix\none\n\n'
        with patch.object(plugin, 'date') as clock:
            clock.today.return_value = date(2026, 11, 24)
            plugin.handle(ctx, {'type': 'key', 'key': 'Up'})
            self.assertEqual(ctx.state['index'], 5)
            plugin.handle(ctx, {'type': 'key', 'key': 'Confirm'})
            self.assertEqual(ctx.state['completed'], ['six'])
            clock.today.return_value = date(2026, 11, 25)
            plugin.handle(ctx, {'type': 'interval'})
            self.assertEqual(ctx.state['completed'], [])
            self.assertEqual(ctx.state['index'], 0)
