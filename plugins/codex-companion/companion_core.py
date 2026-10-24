"""Metadata-only, restart-safe domain model for the API 1 companion plugin."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
import uuid

LABELS = {'working': '正在工作', 'waiting': '等你处理', 'done': '任务完成',
          'error': '遇到问题', 'stopped': '已停止', 'unknown': '状态待确认'}
TERMINAL = frozenset(('done', 'error', 'stopped'))
TASKS_PER_PAGE = 4
DEFAULT_SETTINGS = dict(codex_enabled=True, animation=True, stale_minutes=15,
                        sound_enabled=False, volume=90, sessions_path='', poll_seconds=3)
EVENT_FIELDS = frozenset(('task_id', 'thread_id', 'seq', 'status', 'title', 'detail', 'progress', 'agent'))
ID = re.compile(r'[A-Za-z0-9_:.-]{1,160}\Z')
SOURCE = re.compile(r'[A-Za-z0-9_.-]{1,48}\Z')
MAX_READ = 2 * 1024 * 1024
MAX_TAIL = 4 * 1024 * 1024


def clean(text, limit):
    return ''.join(c for c in text if not unicodedata.category(c).startswith('C'))[:limit]


def _id(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_event(event):
    if not isinstance(event, dict) or set(event) - EVENT_FIELDS:
        raise ValueError('Unsupported event fields')
    if not _id(event.get('task_id')) or type(event.get('seq')) is not int or not 0 < event['seq'] < 2**64:
        raise ValueError('Invalid task id or sequence')
    if event.get('thread_id') is not None and not _id(event['thread_id']):
        raise ValueError('Invalid thread id')
    if not isinstance(event.get('status'), str) or event['status'] not in LABELS:
        raise ValueError('Invalid status')
    result = dict(event)
    for key, limit in (('title', 120), ('detail', 240), ('agent', 40)):
        value = event.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Invalid text length or type')
        result[key] = clean(value.strip() if key == 'title' else value, limit)
    if not result['title']:
        raise ValueError('Title must not be empty')
    progress = event.get('progress')
    if progress is not None and (type(progress) is not int or not 0 <= progress <= 100):
        raise ValueError('Progress must be an integer between 0 and 100')
    result.setdefault('thread_id', None)
    result.setdefault('progress', None)
    return result


def task_key(task):
    return task['source'] + ':' + task['event']['task_id']


def task_status(task):
    status = task['event']['status']
    return 'unknown' if task.get('stale') and status not in TERMINAL else status


def task_label(task):
    if task_status(task) == 'waiting' and task['event'].get('detail', '').startswith('权限审批'):
        return '等待权限审批'
    return LABELS[task_status(task)]


class Model:
    def __init__(self, state, settings, now):
        self.state = state
        self.settings = dict(DEFAULT_SETTINGS, **settings)
        self.now = now
        state.setdefault('tasks', [])
        state.setdefault('selected', None)
        state.setdefault('approvals', {'requests': [], 'closed_turns': []})
        self.tasks = state['tasks']

    def dump(self):
        self.compact()
        return self.state

    def compact(self):
        # Host adds a small view summary; reserve at least 8 KiB for that.
        size = lambda: len(json.dumps(self.state, ensure_ascii=True).encode())
        while len(self.tasks) > 1 and size() > 56000:
            self.tasks.pop()
        approvals = self.state['approvals']
        if size() > 56000:
            for request in approvals['requests']:
                request['title'] = ''
                request['tool_name'] = request['tool_name'] if request['tool_name'] in ('Bash', 'apply_patch') else ''
        while approvals['closed_turns'] and size() > 56000:
            approvals['closed_turns'].pop(0)
        while self.tasks and size() > 56000:
            self.tasks.pop()

    def _bound(self):
        del self.tasks[32:]
        # Keep ample headroom for 24 watcher cursors, receipts and renderer state.
        while self.tasks and len(json.dumps(self.tasks, ensure_ascii=True).encode()) > 28000:
            self.tasks.pop()

    def apply(self, event, source='agent', at=None):
        event = validate_event(event)
        if not isinstance(source, str) or SOURCE.fullmatch(source) is None:
            raise ValueError('Invalid source namespace')
        at = self.now if at is None else at
        if not _number(at) or at > self.now + 10 or at < 0:
            raise ValueError('Invalid timestamp')
        existing = next((t for t in self.tasks if t['source'] == source and t['event']['task_id'] == event['task_id']), None)
        if existing:
            if event['seq'] <= existing['event']['seq'] or existing['event']['status'] in TERMINAL or at < existing['updated_at']:
                return False
            self.tasks.remove(existing)
        self.tasks.append(dict(event=event, source=source, updated_at=at, stale=False))
        self.tasks.sort(key=lambda t: (t['updated_at'], t['event']['seq']), reverse=True)
        self._bound()
        self.compact()
        return True

    def visible(self):
        tasks = [copy.deepcopy(t) for t in self.tasks if t['source'] != 'codex' or self.settings['codex_enabled']]
        if self.settings['codex_enabled']:
            for approval in self.state['approvals']['requests']:
                if approval['resolved']:
                    continue
                task = next((t for t in tasks if t['source'] == 'codex' and t['event']['task_id'] == approval['turn_id'] and t['event'].get('thread_id') == approval['thread_id']), None)
                if task and task['event']['status'] in TERMINAL:
                    continue
                if task is None:
                    task = dict(event=dict(task_id=approval['turn_id'], thread_id=approval['thread_id'], seq=0, status='waiting', title=approval['title'] or 'Codex 权限审批', detail='', progress=None, agent='Codex'), source='codex', updated_at=approval['at'], stale=False)
                    tasks.append(task)
                task['event']['status'] = 'waiting'
                tool = approval['tool_name']
                task['event']['detail'] = '权限审批 · ' + ('执行命令' if tool == 'Bash' else '修改文件' if tool == 'apply_patch' else '工具访问')
                task['updated_at'] = max(task['updated_at'], approval['at'])
        tasks.sort(key=lambda t: (t['updated_at'], t['event']['seq']), reverse=True)
        for task in tasks:
            task['stale'] = self.now - task['updated_at'] > self.settings['stale_minutes'] * 60
        return tasks

    def live(self):
        result, seen = [], set()
        for task in self.visible():
            thread = task['event'].get('thread_id')
            if task['source'] == 'codex' and thread:
                if thread in seen:
                    continue
                seen.add(thread)
            result.append(task)
        return result

    def running(self):
        return sorted((t for t in self.live() if task_status(t) in ('working', 'waiting')),
                      key=lambda t: (t['source'], t['event'].get('thread_id') or t['event']['task_id']))

    def current(self):
        active = self.running()
        tasks = active if len(active) > 1 else self.live()
        selected = next((t for t in tasks if task_key(t) == self.state['selected']), None)
        if selected:
            return selected
        live = self.live()
        return next((t for t in live if task_status(t) == 'waiting'), None) or next((t for t in live if task_status(t) == 'working'), None) or (live[0] if live else None)

    def cycle(self, step):
        active = self.running()
        tasks = active if len(active) > 1 else self.live()
        if not tasks:
            self.state['selected'] = None
            return
        if len(active) > TASKS_PER_PAGE:
            idx = next((i for i, t in enumerate(active) if task_key(t) == self.state['selected']), 0)
            pages = (len(active) + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE
            idx = ((idx // TASKS_PER_PAGE + step) % pages) * TASKS_PER_PAGE
        else:
            current = self.current()
            idx = next((i for i, t in enumerate(tasks) if task_key(t) == task_key(current)), 0)
            idx = (idx + step) % len(tasks)
        self.state['selected'] = task_key(tasks[idx])

    def apply_approval(self, signal):
        allowed = {'event', 'thread_id', 'turn_id', 'request_id', 'tool_name', 'title', 'at'}
        if not isinstance(signal, dict) or set(signal) - allowed:
            raise ValueError('Invalid approval fields')
        event = signal.get('event')
        if event not in ('PermissionRequest', 'PostToolUse', 'Stop', 'Interrupt', 'SessionEnd') or not _id(signal.get('thread_id')):
            raise ValueError('Invalid approval event')
        s = dict(turn_id='', request_id='', tool_name='', title='') | signal
        for key in ('turn_id', 'request_id'):
            if s[key] and not _id(s[key]):
                raise ValueError('Invalid approval identifier')
        if event in ('PermissionRequest', 'PostToolUse') and not (_id(s['turn_id']) and _id(s['request_id'])):
            raise ValueError('Approval requires turn and request ids')
        if not _number(s.get('at')) or not self.now - 30 <= s['at'] <= self.now + 10:
            raise ValueError('Approval is expired')
        for key, limit in (('title', 120), ('tool_name', 80)):
            if not isinstance(s[key], str) or len(s[key]) > limit:
                raise ValueError('Invalid approval text')
            s[key] = clean(s[key], limit)
        approvals = self.state['approvals']
        if event == 'PermissionRequest':
            if any(c[0] == s['thread_id'] and (not c[1] or c[1] == s['turn_id']) and c[2] >= s['at'] for c in approvals['closed_turns']):
                return False
            if any(all(r[k] == s[k] for k in ('thread_id', 'turn_id', 'request_id')) for r in approvals['requests']):
                return False
            approvals['requests'].append({k:v for k,v in s.items() if k != 'event'} | {'resolved': False})
            del approvals['requests'][:-16]
            self.compact()
            return True
        for r in approvals['requests']:
            if s['at'] >= r['at'] and r['thread_id'] == s['thread_id'] and (not s['turn_id'] or r['turn_id'] == s['turn_id']) and (event != 'PostToolUse' or r['request_id'] == s['request_id']):
                r['resolved'] = True
        if event != 'PostToolUse':
            approvals['closed_turns'].append([s['thread_id'], s['turn_id'], s['at']])
            del approvals['closed_turns'][:-24]
        return False


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _parse(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def _metadata(path):
    with path.open('rb') as f:
        line = f.readline(1024 * 1024 + 1)
    value = _parse(line)
    p = value.get('payload')
    p = p if isinstance(p, dict) else {}
    source = p.get('source')
    subagent = value.get('type') == 'session_meta' and (source == 'subagent' or isinstance(source, dict) and 'subagent' in source)
    return p, subagent


def _collect(root, now, depth=0):
    if depth > 3:
        return []
    result = []
    for path in root.iterdir():
        try:
            if path.is_symlink():
                continue
            if path.is_dir() and path.name.isdecimal():
                result.extend(_collect(path, now, depth + 1))
            elif path.is_file() and path.suffix == '.jsonl':
                modified = path.stat().st_mtime
                if now - modified < 7 * 86400:
                    # Filter before choosing 24 slots. Never inspect copied parent records.
                    meta, child = _metadata(path)
                    if not child:
                        result.append((modified, path, meta))
        except OSError:
            continue
    return result


def _titles(root):
    path = root.parent / 'session_index.jsonl'
    result = {}
    try:
        with path.open('rb') as f:
            size = path.stat().st_size
            f.seek(max(0, size - MAX_TAIL))
            for line in f.read(MAX_TAIL).splitlines():
                v = _parse(line)
                if _id(v.get('id')) and isinstance(v.get('thread_name'), str) and v['thread_name'].strip():
                    result[v['id']] = clean(v['thread_name'].strip(),120)
    except OSError:
        pass
    return result


def _timestamp(value):
    try:
        return max(0, datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 0


def scan_codex(root: Path, cursors: dict, now: float):
    """Advance bounded cursors in caller's transaction; persist them with model state."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError('未找到本机 Codex 会话目录')
    paths = sorted(_collect(root, now), key=lambda item: (item[0],str(item[1])), reverse=True)[:24]
    valid = {_hash(str(path.resolve())) for _,path,_ in paths}
    for key in list(cursors):
        if key not in valid:
            del cursors[key]
    titles = _titles(root)
    newest = {}
    for _, path, meta in paths:
        try:
            size = path.stat().st_size
            key = _hash(str(path.resolve()))
            c = cursors.get(key)
            replaced = False
            if c and c.get('anchor') and size >= c['offset']:
                with path.open('rb') as check:
                    check.seek(max(0, c['offset'] - 64))
                    replaced = hashlib.sha256(check.read(min(64,c['offset']))).hexdigest()[:24] != c['anchor']
            if c is None or size < c['offset'] or replaced:
                thread = meta.get('id') if _id(meta.get('id')) else None
                cwd = meta.get('cwd', '')
                fallback = clean(str(cwd).replace('\\','/').rstrip('/').split('/')[-1],50)
                c = dict(offset=max(0,size-MAX_TAIL), discarding=size>MAX_TAIL, thread=thread, turn=None, state=None, pending={}, title='Codex · '+(fallback or '本机任务'))
                cursors[key] = c
            title = titles.get(c['thread'],c['title'])
            with path.open('rb') as f:
                f.seek(c['offset']); data=f.read(MAX_READ)
            consumed=0
            for line in data.splitlines(keepends=True):
                if not line.endswith(b'\n'):
                    break
                consumed += len(line)
                seq=c['offset']+consumed
                if c['discarding']:
                    c['discarding']=False
                    continue
                if len(line)>1024*1024:
                    continue
                v=_parse(line); p=v.get('payload')
                if not isinstance(p,dict):
                    continue
                kind=p.get('type'); category=v.get('type'); turn=p.get('turn_id')
                status=None
                if category=='event_msg':
                    if kind=='task_started' and _id(turn):
                        if c['turn']==turn and c['state'] in TERMINAL:
                            continue
                        c['turn']=turn; c['pending']={}; status='working'
                    elif kind in ('task_complete','task_completed','turn_aborted'):
                        target=turn if _id(turn) else c['turn']
                        if not target or c['turn'] and target != c['turn']:
                            continue
                        c['turn']=target
                        status='stopped' if kind=='turn_aborted' else 'waiting' if c['pending'] else 'done'
                        if kind=='turn_aborted': c['pending']={}
                    elif kind in ('token_count','item_completed') and c['state']=='working':
                        status='working'
                elif category=='response_item' and c['state'] not in TERMINAL:
                    name=p.get('name','')
                    name=name.rsplit('.',1)[-1] if isinstance(name,str) else ''
                    call=p.get('call_id')
                    if kind=='function_call' and name in ('request_user_input','request_user_input_async') and _id(call):
                        if len(c['pending']) >= 8:
                            # Keep waiting conservatively; never infer all questions answered.
                            c['pending']['overflow']=True
                        else: c['pending'][_hash(call)]=name.endswith('_async')
                        status='waiting'
                    elif kind=='function_call_output' and c['state']=='waiting' and isinstance(call,str) and c['pending'].get(_hash(call)) is False:
                        del c['pending'][_hash(call)]
                        status='waiting' if c['pending'] else 'working'
                    elif kind=='message' and p.get('role')=='user' and c['state']=='waiting':
                        content=p.get('content',[])
                        if isinstance(content,list):
                            for item in content:
                                text=item.get('text','') if isinstance(item,dict) else ''
                                if not isinstance(text,str): continue
                                for envelope in re.findall(r'<send_user_message_question_reply>(.*?)</send_user_message_question_reply>',text,re.S):
                                    # Match exact id tokens, never retain question or answer text.
                                    for token in re.findall(r'[A-Za-z0-9_:.-]+',envelope):
                                        c['pending'].pop(_hash(token),None)
                            status='waiting' if c['pending'] else 'working'
                if status is None or c['turn'] is None:
                    continue
                c['state']=status
                detail={'working':'正在处理本机任务','waiting':'需要你确认，请回到 Codex','done':'本轮 Agent 已结束','stopped':'本轮任务已中止'}[status]
                event=dict(task_id=c['turn'],thread_id=c['thread'],seq=seq,status=status,title=title,detail=detail,progress=None,agent='Codex')
                newest[(c['thread'],c['turn'])]=(event,min(now+10,_timestamp(v.get('timestamp'))))
            if not consumed and len(data)==MAX_READ:
                c['offset']+=len(data); c['discarding']=True
            else: c['offset']+=consumed
            with path.open('rb') as check:
                check.seek(max(0,c['offset']-64))
                c['anchor']=hashlib.sha256(check.read(min(64,c['offset']))).hexdigest()[:24]
        except OSError:
            continue
    return sorted(newest.values(),key=lambda item:(item[1],item[0]['seq']))


def _quarantine(inbox, path):
    # Rename the directory entry itself, including a symlink, without reading its
    # target. Rejected entries no longer occupy the bounded *.json scan window.
    target = inbox / ('_rejected-' + uuid.uuid4().hex + '.bad')
    path.rename(target)
    rejected = sorted((p for p in inbox.glob('_rejected-*.bad')
                       if re.fullmatch(r'_rejected-[a-f0-9]{32}\.bad', p.name)),
                      key=lambda p: p.lstat().st_mtime)
    for old in rejected[:-32]:
        # unlink affects only this known inbox entry, never a symlink target.
        if old.is_symlink() or not old.is_dir():
            old.unlink()


def ingest_inbox(inbox: Path, model: Model, now: float):
    """Acknowledge only receipts loaded from a previous successful worker commit."""
    inbox=Path(inbox)
    stats=dict(accepted=0,rejected=0,replayed=0)
    if not inbox.is_dir():
        model.compact()
        return stats
    old=model.state.pop('inbox_receipts',[])
    for receipt in old:
        name,digest=receipt
        path=inbox/name
        if path.parent != inbox or not re.fullmatch(r'[a-f0-9-]+\.json',name):
            continue
        try:
            if not path.is_symlink() and path.stat().st_size <= 8192 and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
                path.unlink()
        except OSError:
            pass
    receipts=[]
    for path in sorted(inbox.glob('*.json'))[:32]:
        try:
            if path.is_symlink() or path.stat().st_size>8192 or not re.fullmatch(r'[a-f0-9-]+\.json',path.name):
                stats['rejected']+=1
                _quarantine(inbox, path)
                continue
            raw=path.read_bytes(); item=_parse(raw)
            if item.get('kind')=='approval' and set(item)=={'kind','signal'}:
                changed=model.apply_approval(item['signal'])
            elif item.get('kind')=='agent' and set(item) <= {'kind','event','source','at'}:
                source=item.get('source','agent')
                if source in ('codex','demo'):
                    raise ValueError('Reserved namespace')
                changed=model.apply(item['event'],source,item.get('at',now))
            else:
                raise ValueError('Invalid inbox envelope')
            stats['accepted' if changed else 'replayed']+=1
            receipts.append([path.name,hashlib.sha256(raw).hexdigest()])
        except (ValueError,KeyError,TypeError,UnicodeError):
            stats['rejected']+=1
            # Keep a receipt so malformed input cannot starve valid files forever.
            receipts.append([path.name,hashlib.sha256(raw).hexdigest()])
        except OSError:
            stats['rejected']+=1
    model.state['inbox_receipts']=receipts
    model.compact()
    return stats

