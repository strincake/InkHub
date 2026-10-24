"""Write atomic local companion events. No daemon, device or network connection."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time
import uuid
from companion_core import Model, validate_event


def write_event(inbox, event=None, *, source='agent', at=None, approval=None):
    inbox=Path(inbox)
    now=time.time()
    if approval is not None:
        Model({}, {}, now).apply_approval(approval)
        item={'kind':'approval','signal':approval}
    else:
        event=validate_event(event)
        Model({}, {}, now).apply(event,source,at)
        if source in ('codex','demo'):
            raise ValueError('Reserved namespace')
        item={'kind':'agent','source':source,'event':event,'at':now if at is None else at}
    payload=json.dumps(item,ensure_ascii=False,allow_nan=False).encode('utf-8')
    if len(payload)>8192:
        raise ValueError('Event exceeds 8 KiB')
    inbox.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex
    temp=inbox/(name+'.tmp')
    path=inbox/(name+'.json')
    try:
        with temp.open('xb') as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inbox',required=True,type=Path)
    parser.add_argument('--task')
    parser.add_argument('--seq',type=int)
    parser.add_argument('--status',choices=('working','waiting','done','error','stopped','unknown'))
    parser.add_argument('--title',default='')
    parser.add_argument('--detail',default='')
    parser.add_argument('--progress',type=int)
    parser.add_argument('--agent',default='Agent')
    parser.add_argument('--source',default='agent')
    parser.add_argument('--thread')
    parser.add_argument('--at',type=float)
    parser.add_argument('--approval',choices=('PermissionRequest','PostToolUse','Stop','Interrupt','SessionEnd'))
    parser.add_argument('--turn',default='')
    parser.add_argument('--request',default='')
    parser.add_argument('--tool',default='')
    args=parser.parse_args(argv)
    try:
        if args.approval:
            path=write_event(args.inbox,approval=dict(event=args.approval,thread_id=args.thread,turn_id=args.turn,request_id=args.request,tool_name=args.tool,title=args.title,at=time.time() if args.at is None else args.at))
        else:
            if args.task is None or args.seq is None or args.status is None:
                parser.error('Agent events require --task, --seq and --status')
            path=write_event(args.inbox,dict(task_id=args.task,thread_id=args.thread,seq=args.seq,status=args.status,title=args.title,detail=args.detail,progress=args.progress,agent=args.agent),source=args.source,at=args.at)
        print(path.name)
        return 0
    except (ValueError,OSError) as exc:
        parser.error(str(exc))

if __name__=='__main__':
    raise SystemExit(main())
