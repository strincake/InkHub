"""One-time compatibility migration. No gallery execution logic belongs to the host."""
import hashlib,json,shutil,sys,uuid
from pathlib import Path

def migrate(config,template):
    config=Path(config).resolve();template=Path(template).resolve()
    if not config.exists():return {'migrated':0}
    original=config.read_bytes();saved=json.loads(original)
    pools=saved.get('pools',[])
    if not pools:
        if 'pools' in saved:
            saved.pop('pools');config.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'migrated':0}
    root=config.with_suffix('.plugins');packages=root/'packages';packages.mkdir(parents=True,exist_ok=True)
    migrated=[]
    for source,pool in pools:
        legacy_id=source['id'];plugin_id='local-gallery-'+hashlib.sha256(legacy_id.encode()).hexdigest()[:24]
        target=packages/plugin_id;data=root/'data'/plugin_id;record=data/'record.json'
        if target.exists():
            old=json.loads((target/'plugin.json').read_text(encoding='utf-8'))
            if old.get('legacy_source_id')!=legacy_id:raise ValueError('相册迁移目标与现有插件冲突，旧配置未清除')
        else:
            staging=packages/('staging-'+uuid.uuid4().hex)
            shutil.copytree(template,staging,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            manifest=json.loads((staging/'plugin.json').read_text(encoding='utf-8'))
            manifest.update(id=plugin_id,name=('本地相册 · '+source['name'])[:80],legacy_source_id=legacy_id)
            (staging/'plugin.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');staging.rename(target)
        if not record.exists():
            data.mkdir(parents=True,exist_ok=True)
            selected=Path(pool.get('selected','')).name
            if not selected and pool.get('files'):
                selected=Path(pool['files'][pool.get('index',0)%len(pool['files'])]).name
            settings={'folder':pool['folder'],'mode':'固定一张' if pool.get('fixed') else '轮播','order':'随机' if pool.get('shuffle') else '顺序','interval_seconds':max(1,min(86400,pool.get('interval_ms',30000)/1000)),'fixed_image':selected}
            enabled=source.get('enabled',True);rules=dict(source);rules.update(enabled=True,revision=0,consumed=0,order=0,updated_at=0,boost=None)
            payload={'enabled':enabled,'settings':settings,'state':{'current':selected},'source':rules}
            temp=data/'record.tmp';temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(record)
        migrated.append(plugin_id)
    # Only remove the legacy section after every pool has an installed package and durable record.
    backup=config.with_name(config.name+'.before-gallery-plugin-'+uuid.uuid4().hex[:8]+'.bak');backup.write_bytes(original)
    saved.pop('pools',None);temp=config.with_name(config.name+'.gallery-migration.tmp')
    temp.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(config)
    return {'migrated':len(migrated),'plugins':migrated,'backup':backup.name}

def consolidate(config,template):
    """Merge earlier per-pool packages into one plugin, with complete recoverable backups."""
    config=Path(config).resolve();template=Path(template).resolve();root=config.with_suffix('.plugins')
    packages=root/'packages';data=root/'data'
    if not packages.exists():return {'consolidated':0}
    old=[]
    for package in sorted(packages.iterdir()):
        manifest_path=package/'plugin.json'
        if not manifest_path.is_file():continue
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if not (manifest.get('legacy_source_id') or (manifest.get('id')=='local-gallery' and not manifest.get('multi_channel'))):continue
        record_path=data/package.name/'record.json'
        if not record_path.is_file():raise ValueError('旧相册缺少设置记录，保留原插件')
        old.append((package,json.loads(record_path.read_text(encoding='utf-8'))))
    if not old:return {'consolidated':0}
    target=packages/'local-gallery';record=data/'local-gallery'/'record.json'
    existing=None
    if target.exists() and all(p!=target for p,_ in old):
        m=json.loads((target/'plugin.json').read_text(encoding='utf-8'))
        if not m.get('multi_channel'):raise ValueError('local-gallery ID 冲突')
        existing=json.loads(record.read_text(encoding='utf-8'))
    sources=list(existing['settings']['sources']) if existing else []
    states=dict(existing.get('state',{}).get('albums',{})) if existing else {}
    channels=dict(existing.get('channels',{})) if existing else {}
    known={a['id'] for a in sources}
    for package,payload in old:
        key='album-'+hashlib.sha256(package.name.encode()).hexdigest()[:16]
        if key in known:continue
        rules=dict(payload['source']);settings=dict(payload['settings'])
        settings.update(id=key,name=rules['name'],enabled=payload['enabled'] and rules.get('enabled',True),fit=rules.get('fit','contain'))
        settings['rules']={k:v for k,v in rules.items() if k in ('priority','min_ms','hold_ms','ttl_ms','persistent','bypass','format')}
        sources.append(settings);states[key]=payload.get('state',{});channels[key]={**rules,'enabled':settings['enabled']}
    if len(sources)>32:raise ValueError('旧相册超过 32 个，未合并')
    backup=root/'migration-backups'/('gallery-'+uuid.uuid4().hex);backup.mkdir(parents=True)
    # Back up both package and private data before writing the merged target.
    for package,_ in old:
        shutil.copytree(package,backup/'packages'/package.name)
        if (data/package.name).exists():shutil.copytree(data/package.name,backup/'data'/package.name)
    if existing:
        shutil.copytree(target,backup/'combined-package');shutil.copytree(record.parent,backup/'combined-data')
    merged=existing or dict(old[0][1]);merged.update(enabled=bool((existing or {}).get('enabled')) or any(p['enabled'] for _,p in old),settings={'sources':sources},state={'albums':states},channels=channels)
    # Persist settings first; if interrupted, stable source IDs make the next run idempotent.
    record.parent.mkdir(parents=True,exist_ok=True)
    temp=record.with_suffix('.merge.tmp');temp.write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(record)
    target.mkdir(exist_ok=True)
    for file in template.iterdir():
        if file.is_file():shutil.copy2(file,target/file.name)
    for package,_ in old:
        if package==target:continue
        if package.resolve().parent!=packages.resolve():raise ValueError('相册路径越界')
        package.rename(backup/('retired-'+package.name))
        private=data/package.name
        if private.exists():
            if private.resolve().parent!=data.resolve():raise ValueError('相册数据路径越界')
            private.rename(backup/('retired-data-'+package.name))
    return {'consolidated':len(old),'backup':str(backup)}

if __name__=='__main__':
    try:
        result=migrate(sys.argv[1],sys.argv[2]);result.update(consolidate(sys.argv[1],sys.argv[2]));print(json.dumps(result,ensure_ascii=False))
    except Exception as error:print(str(error),file=sys.stderr);sys.exit(1)
