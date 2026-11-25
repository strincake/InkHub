"""AI authoring bridge. Generated code is inspected, never imported or executed."""
import ast
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# Embedded Python uses an isolated ._pth and omits the script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugin_tools import member_name, validate_manifest, inspect_package

LIMIT = 2 * 1024 * 1024
PROTOCOL = '2025-06-18'


def url_check(url, local=False):
    p = urllib.parse.urlsplit(url)
    if p.username or p.password or p.fragment or not p.hostname:
        raise ValueError('Endpoint 格式不正确')
    loopback = p.hostname in ('localhost', '127.0.0.1', '::1')
    if p.scheme != 'https' and not (p.scheme == 'http' and loopback):
        raise ValueError('远程 API 请使用 HTTPS；本地服务可使用 HTTP')
    if local and not loopback:
        raise ValueError('本地 MCP 仅接受 localhost、127.0.0.1 或 ::1')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('服务返回重定向，请填写最终 Endpoint')


def http_json(url, payload, headers, sse_id=None):
    req = urllib.request.Request(url_check(url), json.dumps(payload).encode(), headers, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=160) as response:
            session = response.headers.get('Mcp-Session-Id')
            if 'text/event-stream' in response.headers.get('content-type', ''):
                data, total = [], 0
                for line in response:
                    total += len(line)
                    if total > LIMIT:
                        raise ValueError('服务响应过大')
                    line = line.decode('utf-8').rstrip('\r\n')
                    if line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        item = json.loads('\n'.join(data)); data = []
                        if item.get('id') == sse_id:
                            return item, session
                raise ValueError('MCP 流已结束，但未返回本次请求结果')
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('服务响应过大')
            return (json.loads(raw) if raw else {}), session
    except urllib.error.HTTPError as e:
        # Do not echo provider bodies: they may contain credentials or request data.
        raise ValueError(f'服务返回 HTTP {e.code}，请检查 Endpoint、密钥、模型及额度') from None
    except urllib.error.URLError:
        raise ValueError('无法连接服务，请检查地址、网络与本地服务是否启动') from None


class MCP:
    def __init__(self, config):
        self.config, self.process, self.timer = config, None, None
        self.session, self.sequence, self.protocol = None, 0, PROTOCOL

    def __enter__(self):
        if self.config.get('transport') == 'stdio':
            command, args = self.config.get('command', ''), self.config.get('args', [])
            env = self.config.get('env', {})
            if not command or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError('填写 MCP 程序路径及 JSON 参数数组')
            if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
                raise ValueError('MCP 环境变量应为字符串 JSON 对象')
            self.process = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, env={**os.environ, **env},
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.timer = threading.Timer(200, self.process.kill)
            self.timer.start()
        else:
            url_check(self.config.get('url', ''), local=True)
        try:
            result = self.rpc('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {},
                                            'clientInfo': {'name': 'InkHub', 'version': '0.1.1'}})
            self.protocol = result.get('protocolVersion', PROTOCOL)
            self.rpc('notifications/initialized', None, notify=True)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.timer:
            self.timer.cancel()
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
            self.process.stdin.close(); self.process.stdout.close()

    def rpc(self, method, params=None, notify=False):
        self.sequence += 1
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        if not notify:
            message['id'] = self.sequence
        if self.process:
            self.process.stdin.write(json.dumps(message).encode() + b'\n'); self.process.stdin.flush()
            if notify:
                return {}
            total = 0
            while True:
                line = self.process.stdout.readline(LIMIT + 1)
                total += len(line)
                if not line:
                    raise ValueError('MCP 进程退出或超时')
                if total > LIMIT:
                    raise ValueError('MCP 响应过大')
                result = json.loads(line)
                if result.get('id') == message['id']:
                    break
                # No client sampling / roots / elicitation capabilities were advertised.
                if 'method' in result and 'id' in result:
                    reply = {'jsonrpc': '2.0', 'id': result['id'], 'error': {'code': -32601, 'message': 'Unsupported client request'}}
                    self.process.stdin.write(json.dumps(reply).encode() + b'\n'); self.process.stdin.flush()
        else:
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                       'MCP-Protocol-Version': self.protocol}
            if self.session:
                headers['Mcp-Session-Id'] = self.session
            if self.config.get('token'):
                headers['Authorization'] = 'Bearer ' + self.config['token']
            result, session = http_json(self.config['url'], message, headers, message.get('id'))
            if session:
                self.session = session
            if notify:
                return {}
        if 'error' in result:
            raise ValueError('MCP 请求失败，请检查工具名称、参数及服务日志')
        if result.get('id') != message['id'] or 'result' not in result:
            raise ValueError('MCP 未返回匹配的 JSON-RPC 结果')
        return result['result']


def parse_object(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('AI 应返回包含 files 的 JSON 对象')
    return result


def package(result):
    files = result.get('files')
    if not isinstance(files, dict) or not 2 <= len(files) <= 64:
        raise ValueError('AI 未返回有效 files 对象（2～64 个文本文件）')
    checked, size = {}, 0
    for name, content in files.items():
        if not isinstance(content, str):
            raise ValueError('生成文件内容必须为文本')
        safe = member_name(name)
        if safe != name or safe.casefold() in {n.casefold() for n in checked}:
            raise ValueError('生成文件路径不规范或重复')
        size += len(content.encode())
        if size > LIMIT:
            raise ValueError('生成的代码超过 2 MiB')
        if name.endswith('.py'):
            ast.parse(content, filename=name)
        checked[name] = content
    manifest = validate_manifest(json.loads(checked.get('plugin.json', '{}')), set(checked))
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in checked.items():
            archive.writestr(name, content.encode())
    inspect_package(data.getvalue())
    summary = result.get('summary', '')
    if not isinstance(summary, str):
        summary = ''
    return {'manifest': manifest, 'files': checked, 'summary': summary[:8000],
            'zip_base64': base64.b64encode(data.getvalue()).decode()}


def substitute(value, prompt, instructions):
    if isinstance(value, str):
        # A single pass prevents placeholders in user input from being expanded again.
        import re
        return re.sub(r'\{\{(prompt|instructions)\}\}', lambda m: prompt if m[1] == 'prompt' else instructions, value)
    if isinstance(value, dict):
        return {k: substitute(v, prompt, instructions) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, prompt, instructions) for v in value]
    return value


def generate(request):
    prompt = request.get('prompt', '').strip()
    if not prompt or len(prompt) > 12000:
        raise ValueError('请填写 1～12000 字的插件需求')
    instructions = request['instructions'] + '\n只返回 JSON：{"files":{"plugin.json":"完整文本","main.py":"完整文本"},"summary":"说明"}。文件不可省略，不要运行、安装代码或写入本机文件。'
    if request.get('mode') == 'mcp':
        config = request['mcp']
        arguments = config.get('arguments')
        if not isinstance(arguments, dict) or not config.get('tool'):
            raise ValueError('请选择 MCP 生成工具并填写 JSON 参数对象')
        template = json.dumps(arguments, ensure_ascii=False)
        if '{{prompt}}' not in template or '{{instructions}}' not in template:
            raise ValueError('MCP 参数需包含 {{prompt}} 和 {{instructions}} 占位符')
        with MCP(config) as client:
            result = client.rpc('tools/call', {'name': config['tool'], 'arguments': substitute(arguments, prompt, instructions)})
        if result.get('isError'):
            raise ValueError('MCP 工具执行失败，请检查工具参数或服务日志')
        structured = result.get('structuredContent', {})
        if isinstance(structured, dict) and 'files' in structured:
            return package(structured)
        text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
    else:
        config = request['api']
        endpoint, model = config.get('endpoint', '').strip().rstrip('/'), config.get('model', '').strip()
        if not model:
            raise ValueError('请填写服务商支持的模型名称')
        headers = {'Content-Type': 'application/json'}
        if config.get('protocol') == 'anthropic':
            url = endpoint if endpoint.endswith('/messages') else endpoint + '/messages'
            headers.update({'x-api-key': config.get('key', ''), 'anthropic-version': '2023-06-01'})
            payload = {'model': model, 'max_tokens': 16384, 'system': instructions,
                       'messages': [{'role': 'user', 'content': prompt}]}
            result, _ = http_json(url, payload, headers)
            text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
        else:
            url = endpoint if endpoint.endswith('/chat/completions') else endpoint + '/chat/completions'
            if config.get('key'):
                headers['Authorization'] = 'Bearer ' + config['key']
            payload = {'model': model, 'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': prompt}]}
            result, _ = http_json(url, payload, headers)
            text = result['choices'][0]['message']['content']
    return package(parse_object(text))


def run(request):
    if request.get('op') == 'tools':
        with MCP(request['mcp']) as client:
            tools, cursor = [], None
            for _ in range(20):
                result = client.rpc('tools/list', {'cursor': cursor} if cursor else {})
                tools.extend(result.get('tools', []))
                cursor = result.get('nextCursor')
                if not cursor:
                    return {'tools': tools}
            raise ValueError('MCP 工具列表分页过多')
    if request.get('op') == 'skill':
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('inkhub-plugin/SKILL.md', request['skill'])
            archive.writestr('inkhub-plugin/references/plugin-development.md', request['guide'])
        return {'zip_base64': base64.b64encode(data.getvalue()).decode()}
    return generate(request)


if __name__ == '__main__':
    try:
        request = json.loads(sys.stdin.buffer.read(256 * 1024))
        result = run(request)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode())
    except Exception as e:
        message = str(e) if isinstance(e, (ValueError, SyntaxError)) else '生成失败，请检查连接配置、模型输出和服务状态'
        sys.stdout.buffer.write(json.dumps({'error': message}, ensure_ascii=False).encode())
        sys.exit(1)
