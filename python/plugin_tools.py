"""ZIP inspection/install only. This module never imports plugin code."""
import io,json,re,stat,sys,uuid,zipfile,shutil
from pathlib import Path,PurePosixPath
SLUG=re.compile(r'^[a-z][a-z0-9_-]{0,47}$')
def member_name(name):
    if not name or '\\' in name or ':' in name or name.startswith('/') or any(ord(c)<32 for c in name):
        raise ValueError('插件包含不安全路径')
    parts=name.rstrip('/').split('/')
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    if any(p in ('','.','..') or p.endswith((' ','.')) or p.split('.')[0].upper() in reserved or any(c in p for c in '<>"|?*') for p in parts):
        raise ValueError('插件包含不安全路径')
    return '/'.join(parts)
def validate_settings(fields,values):
    if not isinstance(values,dict):raise ValueError('设置应为 JSON 对象')
    known={f['key'] for f in fields}
    if set(values)-known:raise ValueError('设置中包含未声明字段')
    result={}
    for f in fields:
        value=values.get(f['key'],f.get('default',{'text':'','password':'','textarea':'','boolean':False,'number':0,'select':(f.get('options') or [''])[0],'json':[]}[f['type']]))
        if f['type']=='json':valid=isinstance(value,(list,dict)) and len(json.dumps(value,ensure_ascii=False).encode())<=32768
        elif f['type']=='boolean':valid=isinstance(value,bool)
        elif f['type']=='number':valid=isinstance(value,(int,float)) and not isinstance(value,bool) and f.get('min',-1e15)<=value<=f.get('max',1e15)
        else:valid=isinstance(value,str) and len(value)<=4096
        if f['type']=='select':valid=valid and value in f['options']
        if not valid:raise ValueError('设置字段类型或范围错误：'+f['key'])
        result[f['key']]=value
    return result
def validate_manifest(m,names):
    if not isinstance(m,dict) or type(m.get('api_version')) is not int or m.get('api_version')!=1:raise ValueError('仅支持插件 API 1')
    if not SLUG.fullmatch(m.get('id','')):raise ValueError('插件 ID 应为小写字母开头的英文标识')
    for key in ('name','version'):
        if not isinstance(m.get(key),str) or not 1<=len(m[key])<=80:raise ValueError('插件缺少名称或版本')
    if not isinstance(m.get('description',''),str) or len(m.get('description',''))>1000:raise ValueError('插件介绍过长')
    entry=member_name(m.get('entry','main.py'))
    if entry not in names or not entry.endswith('.py'):raise ValueError('找不到插件 Python 入口')
    m['entry']=entry
    for key in ('homepage','settings_page'):
        if key in m:
            if not isinstance(m[key],str):raise ValueError('插件主页路径应为字符串')
            page=member_name(m[key])
            if page not in names or not page.endswith('.html'):raise ValueError('找不到插件主页 HTML')
    if 'navigation_title' in m and (not isinstance(m['navigation_title'],str) or not 1<=len(m['navigation_title'].strip())<=40):raise ValueError('导航标题应为 1～40 个字符')
    if 'multi_channel' in m and not isinstance(m['multi_channel'],bool):raise ValueError('multi_channel 应为布尔值')
    triggers=m.get('triggers',{})
    if not isinstance(triggers,dict) or set(triggers)-{'startup','interval_seconds','keys','displayed','actions'}:raise ValueError('未知触发器配置')
    for key in ('startup','keys','displayed'):
        if key in triggers and not isinstance(triggers[key],bool):raise ValueError('触发器开关应为布尔值')
    if 'interval_seconds' in triggers and (not isinstance(triggers['interval_seconds'],(int,float)) or isinstance(triggers['interval_seconds'],bool) or not 1<=triggers['interval_seconds']<=86400):raise ValueError('定时间隔应为 1～86400 秒')
    actions=triggers.get('actions',[])
    if not isinstance(actions,list) or len(actions)>12:raise ValueError('手动操作最多 12 个')
    seen=set()
    for action in actions:
        if not isinstance(action,dict) or not SLUG.fullmatch(action.get('id','')) or action['id'] in seen or not isinstance(action.get('label'),str) or not 1<=len(action['label'])<=40:raise ValueError('手动操作定义错误')
        seen.add(action['id'])
    source=m.get('source_defaults',{})
    if not isinstance(source,dict) or set(source)-{'priority','min_ms','hold_ms','ttl_ms','persistent','bypass','format','fit'}:raise ValueError('默认显示规则包含不支持的字段')
    for key in ('persistent','bypass'):
        if key in source and not isinstance(source[key],bool):raise ValueError('默认显示规则开关类型错误')
    for key,maximum in (('priority',5),('min_ms',86400000),('hold_ms',604800000),('ttl_ms',604800000)):
        if key in source and (type(source[key]) is not int or not (1 if key=='priority' else 0)<=source[key]<=maximum):raise ValueError('默认显示规则数值错误')
    if 'format' in source and source['format'] not in ('mono','gray4','gray16'):raise ValueError('默认灰阶不支持')
    if 'fit' in source and source['fit'] not in ('contain','cover'):raise ValueError('默认填充方式不支持')
    fields=m.get('settings',[])
    if not isinstance(fields,list) or len(fields)>40:raise ValueError('设置字段最多 40 个')
    seen=set()
    for f in fields:
        if not isinstance(f,dict) or not SLUG.fullmatch(f.get('key','')) or f['key'] in seen or f.get('type') not in ('text','password','textarea','number','boolean','select','json'):raise ValueError('设置字段定义错误')
        if not isinstance(f.get('label'),str) or not 1<=len(f['label'])<=80:raise ValueError('设置字段需要清晰的名称')
        if f['type']=='select' and (not isinstance(f.get('options'),list) or not 1<=len(f['options'])<=40 or any(not isinstance(v,str) or len(v)>120 for v in f['options'])):raise ValueError('下拉选项定义错误')
        if 'host_ui' in f and not isinstance(f['host_ui'],bool):raise ValueError('host_ui 应为布尔值')
        for bound in ('min','max'):
            if bound in f and (not isinstance(f[bound],(int,float)) or isinstance(f[bound],bool)):raise ValueError('数字边界应为数字')
        if f.get('min',-1e15)>f.get('max',1e15):raise ValueError('数字范围错误')
        seen.add(f['key'])
    validate_settings(fields,{})
    return m
def inspect_package(data):
    if len(data)>10*1024*1024:raise ValueError('插件 ZIP 不得超过 10 MiB')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries=z.infolist()
        if len(entries)>256 or sum(e.file_size for e in entries)>16*1024*1024:raise ValueError('插件解压体积或文件数量过大')
        names=set();seen=set()
        for entry in entries:
            name=member_name(entry.orig_filename)
            if name.casefold() in seen:raise ValueError('插件包含重名文件')
            seen.add(name.casefold())
            mode=entry.external_attr>>16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)):raise ValueError('插件不允许包含链接或特殊文件')
            if entry.file_size>8*1024*1024 or entry.file_size>max(1,entry.compress_size)*1000:raise ValueError('插件压缩文件展开过大')
            if not entry.is_dir():names.add(name)
        if 'plugin.json' not in names or z.getinfo('plugin.json').file_size>65536:raise ValueError('ZIP 根目录需要 plugin.json')
        manifest=json.loads(z.read('plugin.json').decode('utf-8'))
        return validate_manifest(manifest,names)
def install_package(data,root):
    manifest=inspect_package(data);root=Path(root).resolve();packages=root/'packages';packages.mkdir(parents=True,exist_ok=True)
    target=packages/manifest['id']
    if target.exists():raise ValueError('已安装同 ID 插件；请先卸载，再安装新版本')
    staging=packages/('staging-'+uuid.uuid4().hex);staging.mkdir()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                dest=staging/member_name(info.filename)
                if info.is_dir():dest.mkdir(parents=True,exist_ok=True)
                else:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(info))
        (staging/'plugin.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        staging.rename(target)
    finally:
        if staging.exists() and staging.resolve().parent==packages.resolve():shutil.rmtree(staging)
    return manifest
def export_package(root,plugin_id):
    if not SLUG.fullmatch(plugin_id):raise ValueError('插件 ID 无效')
    root=Path(root).resolve();package=root/'packages'/plugin_id
    if package.resolve().parent!=(root/'packages').resolve():raise ValueError('插件目录越界')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(package.rglob('*')):
            if '__pycache__' in file.parts:continue
            if file.is_symlink() or (hasattr(file,'is_junction') and file.is_junction()):raise ValueError('插件目录含有链接，拒绝导出')
            if file.is_file():
                if not file.resolve().is_relative_to(package.resolve()):raise ValueError('插件文件越界')
                archive.write(file,file.relative_to(package).as_posix())
    data=output.getvalue();inspect_package(data);return data
if __name__=='__main__':
    try:
        if sys.argv[1]=='export':sys.stdout.buffer.write(export_package(sys.argv[2],sys.argv[3]));sys.exit(0)
        if sys.argv[1]=='install':result=install_package(sys.stdin.buffer.read(10*1024*1024+1),Path(sys.argv[2]))
        elif sys.argv[1]=='validate-settings':
            body=json.load(sys.stdin);result=validate_settings(body['fields'],body['values'])
        else:raise ValueError('未知插件操作')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(str(error),file=sys.stderr);sys.exit(1)
