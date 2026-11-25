"""Translate opt-in local Agent hooks into InkHub lifecycle metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from report import write_inbox_item

HOOKS = {
    'claude-code': {
        'UserPromptSubmit': 'start', 'PermissionRequest': 'wait',
        'PostToolUse': 'active', 'PostToolUseFailure': 'active',
        'Stop': 'done', 'StopFailure': 'error', 'SessionEnd': 'stop',
    },
    'gemini-cli': {
        'BeforeAgent': 'start', 'Notification': 'wait', 'AfterTool': 'active',
        'AfterAgent': 'done', 'SessionEnd': 'stop',
    },
    'opencode': {
        'session.execution.started': 'start', 'session.step.started': 'active',
        'session.execution.succeeded': 'done', 'session.execution.failed': 'error',
        'session.execution.interrupted': 'stop', 'permission.asked': 'wait',
        'permission.replied': 'active',
    },
}
MAX_INPUT = 2 * 1024 * 1024


def receive(inbox, source, payload):
    if not isinstance(payload, dict):
        return
    if source == 'opencode':
        hook, data = payload.get('type'), payload.get('data')
        thread = data.get('sessionID') if isinstance(data, dict) else None
    else:
        hook, thread = payload.get('hook_event_name'), payload.get('session_id')
    if not isinstance(hook, str) or not isinstance(thread, str) or not 1 <= len(thread) <= 512:
        return
    if source == 'gemini-cli' and hook == 'Notification' and payload.get('notification_type') != 'ToolPermission':
        return
    action = HOOKS[source].get(hook)
    if action is None:
        return
    seq = time.time_ns()
    item = dict(kind='lifecycle', source=source, action=action, seq=seq, at=seq / 1_000_000_000,
                thread=hashlib.sha256(thread.encode('utf-8')).hexdigest())
    return write_inbox_item(inbox, item, prefix=f'{seq:020d}-')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=HOOKS)
    parser.add_argument('--inbox', required=True, type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) <= MAX_INPUT:
            receive(args.inbox, args.source, json.loads(raw))
    except (ValueError, OSError):
        # Observer failures must not block the Agent or expose the hook payload.
        print('InkHub could not record this lifecycle event.', file=sys.stderr)
    if args.source == 'gemini-cli':
        print('{}')


if __name__ == '__main__':
    main()
