import base64
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python'))
import ai_plugin as ai


def output():
    return {'files': {'plugin.json': json.dumps({'api_version': 1, 'id': 'ai-clock', 'name': 'AI 时钟', 'version': '1.0.0'}),
                      'main.py': 'def handle(ctx, event):\n    ctx.show(ctx.canvas(), "mono")\n'}, 'summary': '时钟'}


class Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append((self.path, body, dict(self.headers)))
        status, result = 200, {}
        if self.path == '/v1/chat/completions':
            result = {'choices': [{'message': {'content': json.dumps(output())}}]}
        elif self.path == '/v1/messages':
            result = {'content': [{'type': 'text', 'text': json.dumps(output())}]}
        elif self.path == '/bad/chat/completions':
            status = 401
            result = {'error': 'secret-key-do-not-echo'}
        else:
            if body['method'] == 'notifications/initialized':
                self.send_response(202); self.end_headers(); return
            if body['method'] == 'initialize':
                value = {'protocolVersion': ai.PROTOCOL, 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'mock', 'version': '1'}}
            elif body['method'] == 'tools/list':
                value = {'tools': [{'name': 'generate', 'inputSchema': {'type': 'object'}}]}
            else:
                value = {'structuredContent': output(), 'content': []}
            result = {'jsonrpc': '2.0', 'id': body['id'], 'result': value}
        raw = json.dumps(result).encode()
        if self.path == '/sse':
            raw = b'event: message\ndata: ' + raw + b'\n\n'
        self.send_response(status)
        self.send_header('Content-Type', 'text/event-stream' if self.path == '/sse' else 'application/json')
        self.send_header('Mcp-Session-Id', 'mock-session')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_generated_zip_is_valid_and_code_not_executed(self):
        result = output(); result['files']['main.py'] = 'raise RuntimeError("must not execute")'
        data = ai.package(result)
        self.assertEqual(ai.inspect_package(base64.b64decode(data['zip_base64']))['id'], 'ai-clock')

    def test_traversal_duplicate_invalid_syntax_and_manifest_rejected(self):
        for name, content in [('../escape.py', 'pass'), ('MAIN.py', 'pass'), ('broken.py', 'def handle('), ('bad.json', None)]:
            with self.subTest(name=name), self.assertRaises((ValueError, SyntaxError)):
                result = output(); result['files'][name] = content; ai.package(result)
        result = output(); result['files']['plugin.json'] = '{}'
        with self.assertRaises(ValueError): ai.package(result)

    def test_api_formats_and_instructions(self):
        for protocol in ['openai', 'anthropic']:
            with self.subTest(protocol=protocol):
                result = ai.generate({'prompt': '中文时钟', 'instructions': 'API guide', 'api': {'endpoint': self.url+'/v1', 'model': 'mock', 'key': 'secret', 'protocol': protocol}})
                self.assertEqual(result['manifest']['id'], 'ai-clock')
                _, payload, headers = Handler.calls[-1]
                self.assertIn('API guide', json.dumps(payload))
                self.assertIn('secret', headers.values()) if protocol == 'anthropic' else self.assertEqual(headers['Authorization'], 'Bearer secret')

    def test_http_errors_do_not_echo_secrets(self):
        with self.assertRaisesRegex(ValueError, 'HTTP 401') as error:
            ai.generate({'prompt': 'clock', 'instructions': '', 'api': {'endpoint': self.url+'/bad', 'model': 'mock'}})
        self.assertNotIn('secret-key', str(error.exception))

    def test_mcp_http_initialization_session_discovery_and_generation(self):
        config = {'url': self.url+'/mcp', 'tool': 'generate', 'arguments': {'prompt': '{{instructions}}\n{{prompt}}'}}
        self.assertEqual(ai.run({'op': 'tools', 'mcp': config})['tools'][0]['name'], 'generate')
        result = ai.generate({'mode': 'mcp', 'prompt': 'clock', 'instructions': 'guide', 'mcp': config})
        self.assertEqual(result['manifest']['id'], 'ai-clock')
        _, payload, headers = Handler.calls[-1]
        self.assertIn('guide', payload['params']['arguments']['prompt'])
        self.assertEqual(headers['Mcp-Session-Id'], 'mock-session')

    def test_mcp_stdio(self):
        config = {'transport': 'stdio', 'command': sys.executable, 'args': [str(ROOT/'tests/support/ai-mcp-mock.py')],
                  'tool': 'generate', 'arguments': {'prompt': '{{instructions}}\n{{prompt}}'}}
        self.assertEqual(ai.run({'op': 'tools', 'mcp': config})['tools'][0]['name'], 'generate')
        result = ai.generate({'mode': 'mcp', 'prompt': 'clock', 'instructions': 'guide', 'mcp': config})
        self.assertEqual(result['manifest']['id'], 'ai-clock')

    def test_mcp_sse_response(self):
        config = {'url': self.url+'/sse', 'tool': 'generate', 'arguments': {'prompt': '{{instructions}}\n{{prompt}}'}}
        self.assertEqual(ai.run({'op': 'tools', 'mcp': config})['tools'][0]['name'], 'generate')
        result = ai.generate({'mode': 'mcp', 'prompt': 'clock', 'instructions': 'guide', 'mcp': config})
        self.assertEqual(result['manifest']['id'], 'ai-clock')

    def test_mcp_requires_both_placeholders(self):
        with self.assertRaisesRegex(ValueError, '占位符'):
            ai.generate({'mode': 'mcp', 'prompt': 'clock', 'instructions': 'guide', 'mcp': {'tool': 'generate', 'arguments': {'prompt': '{{prompt}}'}}})

    def test_placeholder_substitution_does_not_expand_user_text(self):
        self.assertEqual(ai.substitute('{{prompt}} / {{instructions}}', '{{instructions}}', 'guide'), '{{instructions}} / guide')

    def test_endpoint_validation(self):
        for url, local in [('http://example.com', False), ('https://user:key@example.com', False), ('https://example.com/mcp', True), ('file:///etc/passwd', False)]:
            with self.subTest(url=url), self.assertRaises(ValueError): ai.url_check(url, local)
        self.assertEqual(ai.url_check(self.url, True), self.url)

    def test_skill_archive_contains_reference(self):
        import zipfile
        data = ai.run({'op': 'skill', 'skill': 'skill', 'guide': 'guide'})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['zip_base64']))) as archive:
            self.assertEqual(archive.read('inkhub-plugin/references/plugin-development.md'), b'guide')


if __name__ == '__main__': unittest.main()
