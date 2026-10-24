"""All folder scanning, selection and slideshow timing live in this portable plugin."""
import hashlib,json,random
from pathlib import Path
from PIL import Image,ImageOps
EXTENSIONS={'.png','.jpg','.jpeg','.webp','.bmp','.gif','.tif','.tiff'}

def _scan(ctx):
    folder=Path(ctx.settings['folder']).expanduser()
    if not ctx.settings['folder'].strip() or not folder.is_dir():raise ValueError('请在插件设置中填写可读取的图片文件夹')
    files=sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS),key=lambda p:p.name)
    if not files:raise ValueError('文件夹里没有支持的图片；保留最后画面，等待重新扫描')
    if len(files)>2000:raise ValueError('一个相册最多支持 2000 张图片')
    names=[p.name for p in files]
    fingerprint=hashlib.sha256((str(folder.resolve())+'\0'+'\0'.join(names)).encode()).hexdigest()
    if ctx.state.get('fingerprint')!=fingerprint:
        ctx.state['bag']=[];ctx.state['round_started']=False;ctx.state['history']=[];ctx.state['history_pos']=0
    ctx.state['fingerprint']=fingerprint
    listing=[]
    for name in names:
        if len(json.dumps(listing+[name],ensure_ascii=False).encode())>16000:break
        listing.append(name)
    ctx.state.update(files=listing,total=len(files))
    return files,names

def _random_next(ctx,names,current):
    history=ctx.state.get('history',[]);pos=ctx.state.get('history_pos',len(history)-1)
    if pos+1<len(history):ctx.state['history_pos']=pos+1;return history[pos+1]
    bag=ctx.state.get('bag',[])
    if not bag:
        bag=list(range(len(names)))
        if not ctx.state.get('round_started',False):bag=[n for n in bag if names[n]!=current]
        random.shuffle(bag);ctx.state['round_started']=True
        if len(bag)>1 and names[bag[-1]]==current:bag[0],bag[-1]=bag[-1],bag[0]
    name=names[bag.pop()] if bag else current;ctx.state['bag']=bag
    if not history:history=[current]
    history=(history+[name])[-20:];ctx.state['history']=history;ctx.state['history_pos']=len(history)-1
    return name

def _handle_single(ctx,event):
    if event['type']=='displayed':
        if ctx.display['visible'] and ctx.settings['mode']=='轮播':ctx.trigger_after(ctx.settings['interval_seconds'])
        return
    if event['type']=='interval' and (not ctx.display['visible'] or ctx.settings['mode']=='固定一张'):return
    if event['type']=='interval':ctx.require_visible()
    files,names=_scan(ctx)
    if ctx.state.get('order')!=ctx.settings['order']:
        ctx.state.update(order=ctx.settings['order'],bag=[],round_started=False,history=[],history_pos=0)
    current=ctx.state.get('current',names[0]);current=current if current in names else names[0]
    configured=ctx.settings['fixed_image'].strip()
    # Startup keeps a migrated/previous selection. A settings change explicitly applies a new fixed choice.
    if ctx.settings['mode']=='固定一张' and (event['type']=='settings_changed' or 'current' not in ctx.state):
        for file in files:
            if file.name==configured or str(file.resolve())==configured:current=file.name;break
    step=0
    if event['type']=='interval' or event.get('action')=='next' or (event['type']=='key' and event['key']=='Down'):step=1
    if event.get('action')=='previous' or (event['type']=='key' and event['key']=='Up'):step=-1
    if step>0 and ctx.settings['order']=='随机':current=_random_next(ctx,names,current)
    elif step<0 and ctx.settings['order']=='随机' and ctx.state.get('history_pos',0)>0:
        ctx.state['history_pos']-=1;current=ctx.state['history'][ctx.state['history_pos']]
    elif step:current=names[(names.index(current)+step)%len(names)]
    errors=[]
    for offset in range(len(files)):
        file=files[(names.index(current)+offset)%len(files)]
        try:
            with Image.open(file) as original:
                image=ImageOps.exif_transpose(original).convert('RGBA');white=Image.new('RGBA',image.size,'white');white.alpha_composite(image);image=white.convert('RGB')
                if ctx.settings.get('fit','contain')=='cover':image=ImageOps.fit(image,(400,300),Image.Resampling.LANCZOS)
                else:
                    image=ImageOps.contain(image,(400,300),Image.Resampling.LANCZOS);canvas=Image.new('RGB',(400,300),'white');canvas.paste(image,((400-image.width)//2,(300-image.height)//2));image=canvas
            ctx.state['current']=file.name
            ctx.show(image,ctx.display.get('format','mono'))
            if errors:print('已跳过损坏图片：'+', '.join(errors[:5]))
            return
        except (OSError,ValueError) as error:errors.append(file.name)
    raise ValueError('所有图片均无法读取，请检查文件后重新扫描')


def handle(ctx,event):
    # Legacy single-folder callers remain supported, but fit belongs to plugin settings.
    if 'sources' not in ctx.settings:return _handle_single(ctx,event)
    sources=ctx.settings['sources']
    if not isinstance(sources,list) or len(sources)>32:raise ValueError('最多支持 32 个相册来源')
    states=ctx.state.setdefault('albums',{})
    active=set();errors={}
    for item in sources:
        key=item['id']
        if key in active:raise ValueError('相册来源 ID 重复')
        active.add(key)
        rules={**item.get('rules',{}),'enabled':item.get('enabled',True)}
        ch=ctx.register_channel(key,item['name'],rules)
        ch.settings={**{'folder':'','mode':'轮播','order':'顺序','interval_seconds':30,'fixed_image':'','fit':'contain'},**item}
        ch.display['format']=rules.get('format','mono') if event['type']=='settings_changed' else ch.display.get('format',rules.get('format','mono'))
        ch.state=states.setdefault(key,{})
        if not item.get('enabled',True) or rules.get('enabled') is False:continue
        target=event.get('channel')
        if not target and event.get('action') in ('previous','next'):
            target=next((k for k,v in ctx._request.get('channels',{}).items() if v.get('visible')),None)
            if not target:continue
        if target and target!=key:continue
        kind=event['type']
        if kind=='displayed':
            if ch.display.get('visible') and item.get('mode','轮播')=='轮播':
                ch.state['deadline']=ch.display.get('now',0)+float(item.get('interval_seconds',30))*1000
            continue
        if kind=='interval':
            if not ch.display.get('visible') or item.get('mode')=='固定一张':continue
            # Only advance a frame after its own displayed event established a deadline.
            if ch.display.get('now',0)<ch.state.get('deadline',float('inf')):continue
            ch.require_visible();ctx.require_visible()
        try:
            _handle_single(ch,event)
            if ch._shown:ch.state.pop('deadline',None)
        except (OSError,ValueError,KeyError) as error:errors[key]=str(error)
    ctx.state['albums']={k:v for k,v in states.items() if k in active}
    ctx.state['errors']=errors
    if errors:print('；'.join(errors.values()))
