import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

PACKAGE = Path(__file__).resolve().parents[2] / 'plugins' / 'codex-companion'
sys.path.insert(0, str(PACKAGE))
try:
    import companion_core as core
except ModuleNotFoundError:
    core = None

class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, 'domain core must exist')
        self.state = {}
        self.m = core.Model(self.state, {}, 100)

    def ev(self, task='task', seq=1, status='working', **extra):
        return dict(task_id=task, seq=seq, status=status, title='Task') | extra

    def test_sequence_terminal_namespace_and_validation(self):
        self.assertTrue(self.m.apply(self.ev(seq=2)))
        self.assertFalse(self.m.apply(self.ev(seq=1, status='done')))
        self.assertTrue(self.m.apply(self.ev(seq=3, status='done')))
        self.assertFalse(self.m.apply(self.ev(seq=4)))
        self.assertTrue(self.m.apply(self.ev(), 'other'))
        for patch in [dict(progress=True), dict(progress=101), dict(seq=True), dict(title=42), dict(extra='secret')]:
            ev = self.ev(); ev.update(patch)
            with self.assertRaises(ValueError): self.m.apply(ev)
        self.assertEqual(len(self.m.tasks), 2)

    def test_stale_last_turn_stable_rows_page_restart(self):
        for i in range(6): self.m.apply(self.ev(str(i), thread_id='c'+str(i)), 'codex')
        rows = [core.task_key(t) for t in self.m.running()]
        self.m.apply(self.ev('0', 2, 'waiting', thread_id='c0'), 'codex', 101)
        self.assertEqual(rows, [core.task_key(t) for t in self.m.running()])
        self.m.cycle(1)
        self.assertEqual(core.task_key(self.m.current()), rows[4])
        restored = core.Model(json.loads(json.dumps(self.state)), {}, 101)
        self.assertEqual(core.task_key(restored.current()), rows[4])
        self.m.apply(self.ev('new', 3, 'done', thread_id='c0'), 'codex', 102)
        self.assertNotIn('0', [t['event']['task_id'] for t in self.m.live()])
        stale = core.Model(self.state, {}, 2000)
        self.assertEqual(stale.running(), [])
        self.assertIn('unknown', [core.task_status(t) for t in stale.live()])

    def test_approval_dedup_resolution_and_closed_turn(self):
        self.m.apply(self.ev('turn', thread_id='chat'), 'codex')
        signal = dict(event='PermissionRequest',thread_id='chat',turn_id='turn',request_id='req',at=100,tool_name='Bash')
        self.assertTrue(self.m.apply_approval(signal))
        self.assertFalse(self.m.apply_approval(signal))
        self.assertEqual(core.task_label(self.m.current()), '等待权限审批')
        self.m.apply(self.ev('turn', 2, thread_id='chat'), 'codex')
        self.assertEqual(core.task_status(self.m.current()), 'waiting')
        self.m.apply_approval(dict(signal,event='PostToolUse'))
        self.assertEqual(core.task_status(self.m.current()), 'working')
        self.m.apply_approval(dict(signal,event='Stop'))
        self.assertFalse(self.m.apply_approval(dict(signal,request_id='late')))
        with self.assertRaises(ValueError): self.m.apply_approval(dict(signal,at=1))

    def test_watcher_async_privacy_partial_and_no_reopen(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            root = Path(td)/'sessions'; root.mkdir(); path=root/'main.jsonl'
            (root.parent/'session_index.jsonl').write_text(json.dumps(dict(id='chat',thread_name='Chat title'))+'\n')
            cursors={}
            def append(kind,payload):
                with path.open('a',encoding='utf-8') as f: f.write(json.dumps(dict(type=kind,timestamp='1970-01-01T00:01:40Z',payload=payload))+'\n')
            def scan(): return core.scan_codex(root,cursors,100)
            append('session_meta',dict(id='chat',source='vscode',cwd='/work/test',base_instructions='PRIVATE'))
            append('event_msg',dict(type='task_started',turn_id='turn'))
            self.assertEqual(scan()[0][0]['title'],'Chat title')
            append('response_item',dict(type='function_call',name='request_user_input_async',call_id='call',arguments='PRIVATE'))
            self.assertEqual(scan()[0][0]['status'],'waiting')
            cursors=json.loads(json.dumps(cursors))
            append('response_item',dict(type='function_call_output',call_id='call',output='PRIVATE'))
            append('event_msg',dict(type='task_complete',turn_id='turn'))
            self.assertEqual(scan()[0][0]['status'],'waiting')
            append('response_item',dict(type='message',role='user',content=[dict(text='<send_user_message_question_reply>call PRIVATE</send_user_message_question_reply>')]))
            self.assertEqual(scan()[0][0]['status'],'working')
            append('event_msg',dict(type='task_complete',turn_id='turn'))
            self.assertEqual(scan()[0][0]['status'],'done')
            append('event_msg',dict(type='token_count'))
            append('response_item',dict(type='function_call',name='request_user_input',call_id='late'))
            self.assertEqual(scan(),[])
            self.assertNotIn('PRIVATE',json.dumps(cursors))
            with path.open('a') as f: f.write('{"type":')
            self.assertEqual(scan(),[])
            with path.open('a') as f: f.write('"event_msg","payload":{"type":"task_started","turn_id":"next"}}\n')
            self.assertEqual(scan()[0][0]['task_id'],'next')

    def test_subagents_do_not_fill_slots_and_tail_is_bounded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            root=Path(td)
            def write(name, source):
                (root/name).write_text(json.dumps(dict(type='session_meta',payload=dict(id=name,source=source)))+'\n'+json.dumps(dict(type='event_msg',payload=dict(type='task_started',turn_id=name)))+'\n')
            write('parent.jsonl','vscode')
            for i in range(26): write(str(i)+'.jsonl',dict(subagent={}))
            c={}; events=core.scan_codex(root,c,100)
            self.assertEqual(len(events),1)
            self.assertEqual(events[0][0]['task_id'],'parent.jsonl')
            self.assertLess(len(json.dumps(c)),24000)

    def test_inbox_retries_after_failed_worker_and_cli_atomic(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            inbox=Path(td)
            import report
            path=report.write_event(inbox,self.ev(),at=100)
            baseline=json.loads(json.dumps(self.state))
            stats=core.ingest_inbox(inbox,self.m,100)
            self.assertEqual(stats['accepted'],1)
            self.assertTrue(path.exists(), 'retain until persisted receipt proves worker success')
            retry=core.Model(baseline,{},100)
            self.assertEqual(core.ingest_inbox(inbox,retry,100)['accepted'],1)
            restored=core.Model(json.loads(json.dumps(self.state)),{},101)
            self.assertEqual(core.ingest_inbox(inbox,restored,101)['accepted'],0)
            self.assertFalse(path.exists())

    def test_public_state_stays_bounded(self):
        for i in range(200): self.m.apply(self.ev(str(i),title='题'*120,detail='详'*240,agent='人'*40))
        self.assertLess(len(json.dumps(self.state,ensure_ascii=False).encode()),40000)

    def test_combined_worst_case_state_budget(self):
        for i in range(200):
            self.m.apply(self.ev(str(i),title='题'*120,detail='详'*240,agent='人'*40))
        for i in range(16):
            self.m.apply_approval(dict(event='PermissionRequest',thread_id='c'*157+str(i),turn_id='t'*157+str(i),request_id='r'*157+str(i),title='题'*120,tool_name='工'*80,at=100))
        # Cursor upper bound: 24 metadata-only sessions with eight pending ids each.
        self.state['cursors']={str(i):dict(offset=123456789,discarding=False,thread='c'*160,turn='t'*160,state='waiting',pending={str(j)*24:True for j in range(8)},title='题'*120) for i in range(24)}
        self.m.compact()
        self.assertLess(len(json.dumps(self.state).encode()),56000)

    def test_watcher_sync_output_and_initial_tail_do_not_infer_success(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            path=Path(td)/'main.jsonl'; c={}
            def append(kind,payload):
                with path.open('a') as f: f.write(json.dumps(dict(type=kind,payload=payload))+'\n')
            append('session_meta',dict(id='chat'))
            with path.open('a') as f: f.write('x'*(core.MAX_TAIL+10)+'\n')
            append('event_msg',dict(type='token_count'))
            self.assertEqual(core.scan_codex(Path(td),c,100),[])
            self.assertEqual(core.scan_codex(Path(td),c,100),[])
            append('event_msg',dict(type='task_started',turn_id='new'))
            self.assertEqual(core.scan_codex(Path(td),c,100)[0][0]['status'],'working')
            append('response_item',dict(type='function_call',name='functions.request_user_input',call_id='sync'))
            self.assertEqual(core.scan_codex(Path(td),c,100)[0][0]['status'],'waiting')
            append('response_item',dict(type='function_call_output',call_id='sync',output='PRIVATE'))
            self.assertEqual(core.scan_codex(Path(td),c,100)[0][0]['status'],'working')

    def test_watcher_replaced_same_size_file_resets_cursor(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            path=Path(td)/'main.jsonl'; c={}
            def content(turn): return json.dumps(dict(type='session_meta',payload=dict(id='chat'))) + '\n' + json.dumps(dict(type='event_msg',payload=dict(type='task_started',turn_id=turn))) + '\n'
            path.write_text(content('old'))
            self.assertEqual(core.scan_codex(Path(td),c,100)[0][0]['task_id'],'old')
            path.write_text(content('new'))
            self.assertEqual(core.scan_codex(Path(td),c,100)[0][0]['task_id'],'new')

    def test_namespaces_cannot_collide_with_task_key_separator(self):
        self.m.apply(self.ev('b:c'), 'a')
        for source in ('a:b', 'x'*49, '', 'bad space'):
            with self.assertRaises(ValueError): self.m.apply(self.ev('c'),source)
        self.m.apply(self.ev('c'),'a.b-c_1')
        self.assertEqual(len({core.task_key(t) for t in self.m.live()}),2)
        import report
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            with self.assertRaises(ValueError): report.write_event(Path(td),self.ev('c'),source='a:b',at=100)
            self.assertEqual(list(Path(td).iterdir()),[])

    def test_old_approval_ack_does_not_clear_newer_request(self):
        s=dict(event='PermissionRequest',thread_id='chat',turn_id='turn',request_id='req',at=100)
        self.m.apply_approval(s)
        self.m.apply_approval(dict(s,event='PostToolUse',at=99))
        self.assertFalse(self.state['approvals']['requests'][0]['resolved'])
        self.m.apply_approval(dict(s,event='Stop',at=99))
        self.assertFalse(self.state['approvals']['requests'][0]['resolved'])
        self.m.apply_approval(dict(s,event='PostToolUse',at=100))
        self.assertTrue(self.state['approvals']['requests'][0]['resolved'])

    def test_invalid_inbox_entries_cannot_starve_later_valid_reports(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            inbox=Path(td)
            for i in range(32): (inbox/(f'{i:032x}'+'.json')).write_bytes(b'x'*8193)
            event=dict(kind='agent',event=self.ev(),at=100)
            good=inbox/('f'*32+'.json'); good.write_text(json.dumps(event))
            self.assertEqual(core.ingest_inbox(inbox,self.m,100)['rejected'],32)
            self.assertEqual(core.ingest_inbox(inbox,self.m,100)['accepted'],1)
            self.assertTrue(good.exists())
            self.assertEqual(len(list(inbox.glob('_rejected-*.bad'))),32)
            badname=inbox/'invalid-name.json'; badname.write_text('{}')
            core.ingest_inbox(inbox,self.m,100)
            self.assertFalse(badname.exists())
            self.assertLessEqual(len(list(inbox.glob('_rejected-*.bad'))),32)

    def test_huge_integer_timestamp_rejected_without_blocking_inbox(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as td:
            inbox=Path(td)
            invalid=inbox/('0'*32+'.json')
            invalid.write_text(json.dumps(dict(kind='agent',event=self.ev('bad'),at=10**400)))
            valid=inbox/('f'*32+'.json')
            valid.write_text(json.dumps(dict(kind='agent',event=self.ev('good'),at=100)))
            stats=core.ingest_inbox(inbox,self.m,100)
            self.assertEqual(stats,dict(accepted=1,rejected=1,replayed=0))
            self.assertEqual(self.m.current()['event']['task_id'],'good')
            core.ingest_inbox(inbox,self.m,100)
            self.assertFalse(invalid.exists())

if __name__=='__main__': unittest.main()


