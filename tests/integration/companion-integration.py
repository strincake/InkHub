"""Install the actual ZIP in an isolated host and follow synthetic lifecycle metadata."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
import zipfile
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / 'artifacts/tmp'
TEMP.mkdir(parents=True,exist_ok=True)
RESULTS = ROOT / 'artifacts/tests/integration'
RESULTS.mkdir(parents=True,exist_ok=True)
OUTPUT = ROOT / 'artifacts/tests/integration/companion'
PACKAGE = ROOT / 'plugins' / 'codex-companion'


def wait(fn, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(.12)
    raise AssertionError('Timed out waiting for synthetic plugin state')


def main():
    binary = Path(os.environ.get('SCHEDULER_BINARY', ROOT / 'target/debug/note4-screen-scheduler.exe'))
    opener = build_opener(ProxyHandler({}))
    checks = []
    with tempfile.TemporaryDirectory(prefix='companion-integration-', dir=TEMP) as folder:
        tmp = Path(folder)
        config = tmp / 'settings.json'
        sessions = tmp / 'sessions'
        sessions.mkdir()
        fixture = sessions / 'main.jsonl'
        (tmp / 'session_index.jsonl').write_text(json.dumps({'id': 'chat-main', 'thread_name': '测试：插件任务跟随'}, ensure_ascii=False)+'\n', encoding='utf-8')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        token = None
        process = None

        def start():
            return subprocess.Popen([str(binary), '--port', str(port), '--config', str(config),
                                     '--http-bind', '127.0.0.1:0', '--sdk-bind', '127.0.0.1:0'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

        def call(path, body=None, raw=False):
            headers = {'x-control-token': token} if token else {}
            if body is not None:
                headers['x-control-token'] = token
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                    headers['Content-Type'] = 'application/json'
            try:
                with opener.open(Request(url+path, data=body, headers=headers), timeout=25) as response:
                    data = response.read()
                    return response.status, data if raw else json.loads(data)
            except HTTPError as exc:
                return exc.code, exc.read()

        def state():
            return call('/control/state')[1]

        def plugin():
            return next((p for p in state()['plugins'] if p['id'] == 'codex-companion'), None)

        def command(op, data=None):
            code, result = call('/control/plugins/codex-companion', {'op': op, 'data': data or {}})
            assert code == 200, (code, result)
            return result

        def settled():
            p = plugin()
            return p and p['last_run'] is not None and not p['running'] and not p['pending'] and not p['error'] and p

        def displayed_latest():
            snapshot = state()
            p = next((p for p in snapshot['plugins'] if p['id'] == 'codex-companion'), None)
            shown = snapshot.get('current')
            source = next((s['config'] for s in snapshot['sources'] if p and s['config']['id'] == p['source']), None)
            return p and source and shown and not p['running'] and not p['pending'] and not snapshot['device']['sending'] and shown['frame']['id'] == p['source'] and shown['frame']['revision'] == source['revision']

        def append(kind, payload):
            with fixture.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(type=kind, timestamp=datetime.now(timezone.utc).isoformat(), payload=payload))+'\n')

        def current_status(status):
            p = settled()
            return p and p['state'].get('tasks') and any(t['source'] == 'codex' and t['event']['status'] == status for t in p['state']['tasks'])

        def screenshot(name):
            p = wait(settled)
            raw = call('/control/image/'+p['source'], raw=True)[1]
            image = Image.open(io.BytesIO(raw))
            assert image.size == (400, 300)
            OUTPUT.mkdir(parents=True, exist_ok=True)
            (OUTPUT / f'companion-{name}.png').write_bytes(raw)

        try:
            process = start()
            token = wait(lambda: state()['token'])
            assert call('/control/plugins/install', (ROOT / 'dist/plugins/codex-companion.screen-plugin.zip').read_bytes())[0] == 200
            assert not plugin()['enabled'] and not plugin()['running']
            checks.append('standalone_zip_install_does_not_execute_or_depend_on_old_app')
            values = dict(plugin()['settings'], sessions_path=str(sessions), animation=False, sound_enabled=True)
            command('settings', values)
            append('session_meta', {'id': 'chat-main', 'source': 'vscode', 'cwd': 'C:/synthetic-work'})
            append('event_msg', {'type': 'task_started', 'turn_id': 'turn-main'})
            command('enable')
            wait(lambda: current_status('working'))
            wait(lambda: state()['current'] is not None and not state()['device']['sending'])
            screenshot('working')
            checks.append('startup_and_synthetic_codex_working_400x300')
            # A subagent containing copied parent aborts must not hide the parent.
            child = sessions / 'child.jsonl'
            child.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'child', 'source': {'subagent': {'thread_spawn': {'parent_thread_id': 'chat-main'}}}}})+'\n'+json.dumps({'type': 'event_msg', 'payload': {'type': 'turn_aborted', 'turn_id': 'turn-main'}})+'\n', encoding='utf-8')
            append('response_item', {'type': 'function_call', 'name': 'functions.request_user_input_async', 'call_id': 'question-main', 'arguments': 'PRIVATE_QUESTION_SENTINEL'})
            wait(lambda: current_status('waiting'))
            screenshot('waiting')
            checks.append('async_question_waits_and_child_copied_abort_is_ignored')
            append('response_item', {'type': 'function_call_output', 'call_id': 'question-main', 'output': '{"accepted":true}'})
            append('event_msg', {'type': 'task_complete', 'turn_id': 'turn-main'})
            old = plugin()['last_run']
            wait(lambda: plugin()['last_run'] > old)
            assert current_status('waiting')
            append('response_item', {'type': 'message', 'role': 'user', 'content': [{'text': '<send_user_message_question_reply>question-main PRIVATE_ANSWER_SENTINEL</send_user_message_question_reply>'}]})
            wait(lambda: current_status('working'))
            append('event_msg', {'type': 'task_complete', 'turn_id': 'turn-main'})
            wait(lambda: current_status('done'))
            screenshot('done')
            checks.append('async_acceptance_is_not_answer_resume_then_done')
            record = config.with_suffix('.plugins') / 'data/codex-companion/record.json'
            assert 'PRIVATE_' not in record.read_text(encoding='utf-8')
            assert 'PRIVATE_' not in json.dumps(plugin())
            checks.append('questions_answers_and_tool_arguments_not_persisted')
            inbox = Path(plugin()['state']['_view']['inbox'])
            for i in range(6):
                subprocess.run([sys.executable, str(PACKAGE / 'report.py'), '--inbox', str(inbox), '--task', f'agent-{i}', '--seq', '1', '--status', 'working', '--title', f'测试并行任务 {i}'], check=True, stdout=subprocess.DEVNULL)
            wait(lambda: settled() and len(plugin()['state']['tasks']) >= 7)
            wait(displayed_latest)
            code, _ = call('/control/command', {'op': 'key', 'data': {'key': 'Down'}})
            assert code == 200
            wait(lambda: settled() and plugin()['state'].get('selected') == 'agent:agent-4')
            screenshot('paging')
            checks.append('local_inbox_and_displayed_plugin_key_page_six_tasks')
            command('run', {'action': 'demo-error'})
            wait(lambda: settled() and plugin()['state'].get('_demo') == 'error')
            screenshot('demo-error')
            command('run', {'action': 'auto-follow'})
            wait(lambda: settled() and plugin()['state'].get('_demo') is None and plugin()['state'].get('selected') is None)
            checks.append('manual_demos_are_separate_from_real_state_and_confirm_restores_follow')
            # Export must include only package code/resources, not the fixture or runtime record.
            exported = call('/control/plugins/codex-companion/export', raw=True)[1]
            with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                assert {'main.py', 'companion_core.py', 'plugin.json', 'home.html', 'report.py'} <= set(archive.namelist())
                assert all('record.json' not in n and not n.startswith('data/') for n in archive.namelist())
            assert str(inbox).encode() not in exported
            checks.append('share_exports_only_source_not_local_paths_state_or_fixture')
            command('disable')
            wait(lambda: plugin()['source'] is None and not plugin()['running'])
            command('enable')
            wait(settled)
            assert plugin()['settings'] == values
            call('/control/command', {'op': 'stop'})
            process.wait(10)
            process = start()
            token = wait(lambda: state()['token'])
            wait(settled)
            assert plugin()['enabled'] and plugin()['settings'] == values and len(plugin()['state']['tasks']) >= 7
            checks.append('disable_enable_and_host_restart_preserve_own_settings_and_metadata')
            assert '我已核对这台' not in call('/control/plugin-ui/codex-companion', raw=True)[1].decode()
            checks.append('plugin_homepage_served_without_old_device_confirmation_or_server')
            call('/control/command', {'op': 'stop'})
            process.wait(10)
            result = dict(passed=len(checks), checks=checks, physical_device_tested=False)
            (RESULTS/'companion-integration-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception:
            if process and process.poll() is None:
                process.terminate()
                process.wait(8)
            if process:
                print(process.stderr.read().decode('utf-8', errors='replace'))
            raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(8)


if __name__ == '__main__':
    main()
