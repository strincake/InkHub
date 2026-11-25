"""Deterministic stdio MCP generation fixture; no network or model access."""
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'test-generator', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'generate', 'description': 'Test plugin generator', 'inputSchema': {'type': 'object', 'properties': {'prompt': {'type': 'string'}}, 'required': ['prompt']}}]}
    elif method == 'tools/call':
        result = {'structuredContent': {'files': {'plugin.json': json.dumps({'api_version': 1, 'id': 'ai-clock', 'name': 'AI Clock', 'version': '1.0.0'}), 'main.py': 'def handle(ctx, event):\n    ctx.show(ctx.canvas(), "mono")\n'}, 'summary': 'Generated fixture'}, 'content': []}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
