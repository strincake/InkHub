"""Native short-event companion plugin. The host owns all device operations."""
import hashlib
import json
import os
from pathlib import Path
import time

from companion_core import Model, ingest_inbox, scan_codex, task_key, task_label, task_status
from companion_render import layout, render
from chimes import wav_bytes


def _view(ctx, model, health):
    tasks = model.live()
    current = model.current()
    ctx.state['_view'] = dict(
        health=health,
        mode='演示画面' if ctx.state.get('_demo') else '实时任务',
        current=task_key(current) if current else None,
        total=len(tasks),
        inbox=str(ctx.data_dir / 'inbox'),
        tasks=[dict(title=t['event']['title'], label=task_label(t),
                    source='Codex 本机' if t['source'] == 'codex' else (t['event'].get('agent') or 'Agent'),
                    progress=t['event'].get('progress'), selected=task_key(t) == (task_key(current) if current else None))
               for t in tasks[:12]],
    )


def handle(ctx, event):
    # displayed is a receipt, not a request to recursively generate another picture.
    if event['type'] == 'displayed':
        return
    now = time.time()
    model = Model(ctx.state, ctx.settings, now)
    if event['type'] == 'key':
        ctx.require_visible()
    ctx.trigger_after(max(3, min(60, float(model.settings['poll_seconds']))))
    before = {task_key(t): task_status(t) for t in model.live()}
    first = not ctx.state.get('_initialized') or event['type'] == 'startup'
    health = '本机任务状态正常'

    if model.settings['codex_enabled']:
        configured = model.settings['sessions_path'].strip()
        root = Path(configured).expanduser() if configured else Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions'
        root_key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
        if ctx.state.get('_watch_root') != root_key:
            # A different folder is a different local evidence source, not continuation of old turns.
            ctx.state['_watch_root'] = root_key
            ctx.state['cursors'] = {}
            model.tasks[:] = [t for t in model.tasks if t['source'] != 'codex']
            ctx.state['approvals'] = {'requests': [], 'closed_turns': []}
            if (ctx.state.get('selected') or '').startswith('codex:'):
                ctx.state['selected'] = None
            first = True
        try:
            for value, at in scan_codex(root, ctx.state.setdefault('cursors', {}), now):
                try:
                    model.apply(value, 'codex', at)
                except ValueError:
                    health = '部分无效任务元数据已跳过'
        except (OSError, ValueError):
            health = '未找到可读取的 Codex 会话目录，请检查插件设置'
    else:
        health = 'Codex 跟随已关闭；仍可接收 Agent 状态'
    ingest_inbox(ctx.data_dir / 'inbox', model, now)

    action = event.get('action', '') if event['type'] == 'manual' else ''
    if event['type'] == 'key' or action in ('previous', 'next', 'auto-follow'):
        ctx.state['_demo'] = None
        key = event.get('key') if event['type'] == 'key' else {'previous': 'Up', 'next': 'Down', 'auto-follow': 'Confirm'}[action]
        if key == 'Confirm':
            ctx.state['selected'] = None
        elif key in ('Up', 'Down'):
            model.cycle(-1 if key == 'Up' else 1)
    elif action.startswith('demo-') and action[5:] in ('working', 'waiting', 'done', 'error'):
        ctx.state['_demo'] = action[5:]
    elif action == 'real-tasks':
        ctx.state['_demo'] = None

    # Historical imports and heartbeats do not alert. At most one recent cue per event.
    cue = None
    if not first and not ctx.state.get('_demo'):
        for task in model.live():
            state = task_status(task)
            if state in ('waiting', 'done') and state != before.get(task_key(task)) and not task['stale'] and 0 <= now-task['updated_at'] <= 30:
                if cue is None or state == 'waiting':
                    cue = state
    if action in ('sound-waiting', 'sound-done'):
        # Explicit audition does not turn automatic notifications on.
        cue = action[6:]
    elif not model.settings['sound_enabled']:
        cue = None

    ctx.state['_initialized'] = True
    _view(ctx, model, health)
    if action in ('sound-waiting', 'sound-done'):
        ctx.play_wav(wav_bytes(cue), volume=int(model.settings['volume']))
        model.compact()
        return

    phase = ctx.state.get('_phase', 0)
    current = model.current()
    working = (ctx.state.get('_demo') or (task_status(current) if current else None)) == 'working'
    display = ctx.display
    visible_ms = display.get('now', 0) - (display.get('shown_at') or 0)
    if event['type'] == 'interval' and working and model.settings['animation'] and display.get('visible') and visible_ms >= 2500:
        unchanged = hashlib.sha256(json.dumps(layout(model, phase, ctx.state.get('_demo')), ensure_ascii=False, sort_keys=True).encode()).hexdigest() == ctx.state.get('_picture')
        if unchanged:
            # An animation cannot take the screen back after another source wins during rendering.
            ctx.require_visible()
        phase = (phase+1) % 6
    ctx.state['_phase'] = phase
    elements = layout(model, phase, ctx.state.get('_demo'))
    signature = hashlib.sha256(json.dumps(elements, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    force = event['type'] in ('startup', 'display_settings_changed', 'settings_changed', 'key') or event['type'] == 'manual'
    if force or signature != ctx.state.get('_picture'):
        ctx.show(render(ctx, elements), display.get('format', 'mono'))
        ctx.state['_picture'] = signature
    if cue:
        ctx.play_wav(wav_bytes(cue), volume=int(model.settings['volume']))
    model.compact()
