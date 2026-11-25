import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[2] / 'plugins' / 'codex-companion'
sys.path.insert(0, str(PACKAGE))
from agent_hook import receive
from companion_core import Model, ingest_inbox


class Tests(unittest.TestCase):
    def test_three_frameworks_fold_into_current_task_without_private_payloads(self):
        cases = [
            ('claude-code', ['UserPromptSubmit', 'PermissionRequest', 'PostToolUse', 'Stop']),
            ('gemini-cli', ['BeforeAgent', 'Notification', 'AfterTool', 'AfterAgent']),
            ('opencode', ['session.execution.started', 'permission.asked', 'permission.replied', 'session.execution.succeeded']),
        ]
        with tempfile.TemporaryDirectory() as temp:
            for source, event_names in cases:
                with self.subTest(source=source):
                    model = Model({}, {}, 0)
                    task_ids = []
                    inbox = Path(temp) / source
                    def send(event):
                        payload = dict(session_id='raw-session-id', hook_event_name=event,
                                       notification_type='ToolPermission', prompt='PRIVATE', tool_input={'value': 'PRIVATE'},
                                       type=event, data={'sessionID': 'raw-session-id', 'text': 'PRIVATE'})
                        file = receive(inbox, source, payload)
                        raw = file.read_text(encoding='utf-8')
                        self.assertNotIn('PRIVATE', raw)
                        self.assertNotIn('raw-session-id', raw)
                        now = model.now = time.time()
                        ingest_inbox(inbox, model, now)
                        return model.current()['event']
                    for name, expected in zip(event_names, ['working', 'waiting', 'working', 'done']):
                        event = send(name)
                        task_ids.append(event['task_id'])
                        self.assertEqual(event['status'], expected)
                    self.assertEqual(len(set(task_ids)), 1)
                    self.assertEqual(send(event_names[-1])['status'], 'done')
                    self.assertNotEqual(send(event_names[0])['task_id'], task_ids[0])
                    self.assertEqual(len(model.live()), 1)

    def test_gemini_non_permission_notice_does_not_change_agent_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(PACKAGE / 'agent_hook.py'),
                                     '--source', 'gemini-cli', '--inbox', temp],
                                    input=b'{"session_id":"gemini","hook_event_name":"Notification","notification_type":"Info"}',
                                    capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout), {})
            self.assertEqual(list(Path(temp).iterdir()), [])
