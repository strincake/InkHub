from datetime import datetime
from screen_plugin import ImageDraw

def handle(ctx, event):
    notes=[line.strip() for line in ctx.settings['notes'].splitlines() if line.strip()] or ['写下你的第一条便签。']
    index=ctx.state.get('index',0)
    if event.get('action')=='next-note' or (event['type']=='key' and event['key']=='Down'):
        index+=1
    if event['type']=='key' and event['key']=='Up':
        index-=1
    if event['type']=='key' and event['key']=='Confirm':
        ctx.state['inverted']=not ctx.state.get('inverted',False)
    if event.get('action')=='reset':
        ctx.state.clear();index=0
    ctx.state['index']=index%len(notes)
    ctx.state['runs']=ctx.state.get('runs',0)+1
    dark=(ctx.settings['theme']=='深色') ^ ctx.state.get('inverted',False)
    background,foreground=('black','white') if dark else ('white','black')
    image=ctx.canvas(background);draw=ImageDraw.Draw(image)
    draw.text((22,20),ctx.settings['title'][:18],font=ctx.font(21),fill=foreground)
    draw.line((22,60,378,60),fill=foreground)
    note=notes[ctx.state['index']]
    for row in range(3):
        draw.text((22,96+row*35),note[row*14:(row+1)*14],font=ctx.font(24),fill=foreground)
    clock=datetime.now().strftime('%m-%d  %H:%M') if ctx.settings['show_clock'] else 'DESK NOTE'
    draw.text((22,256),clock,font=ctx.font(16),fill=foreground)
    draw.text((285,256),f"{ctx.state['index']+1} / {len(notes)}",font=ctx.font(16),fill=foreground)
    ctx.show(image,'mono')
    ctx.trigger_after(ctx.settings['refresh_seconds'])
