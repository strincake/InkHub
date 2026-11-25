from math import ceil
from time import time
from screen_plugin import ImageDraw

LABELS = {'focus': '专注时间', 'break': '休息时间'}


def handle(ctx, event):
    now = time()
    timer = ctx.state.get('timer', {})
    action = event.get('action')
    if event['type'] == 'key' and event.get('key') == 'Confirm':
        action = 'toggle'
    if timer.get('mode') == 'running' and timer['deadline'] <= now:
        timer = {'phase': timer['phase'], 'mode': 'done', 'until': timer['deadline'] + 60}
    if action in ('start-focus', 'start-break'):
        phase = 'focus' if action == 'start-focus' else 'break'
        timer = {'phase': phase, 'mode': 'running', 'deadline': now + ctx.settings[phase + '_minutes'] * 60}
    elif action == 'toggle' and timer.get('mode') == 'running':
        timer = {'phase': timer['phase'], 'mode': 'paused', 'remaining': timer['deadline'] - now}
    elif action == 'toggle' and timer.get('mode') == 'paused':
        timer = {'phase': timer['phase'], 'mode': 'running', 'deadline': now + timer['remaining']}
    elif action == 'reset':
        timer = {'mode': 'reset'}
    ctx.state['timer'] = timer

    mode = timer.get('mode', 'idle')
    if mode == 'idle' or (mode == 'done' and timer['until'] <= now):
        return
    image = ctx.canvas()
    draw = ImageDraw.Draw(image)
    draw.text((24, 24), LABELS.get(timer.get('phase'), '专注计时'), font=ctx.font(24), fill='black', anchor='lt')
    if mode in ('running', 'paused'):
        remaining = timer['deadline'] - now if mode == 'running' else timer['remaining']
        minutes = max(1, ceil(remaining / 60))
        draw.text((24, 83), str(minutes), font=ctx.font(100), fill='black', anchor='lt')
        draw.text((24, 200), '分钟剩余', font=ctx.font(22), fill='black', anchor='lt')
        if mode == 'running':
            ctx.trigger_after(max(1, ceil(remaining - (minutes - 1) * 60)))
        footer = '确认键暂停' if mode == 'running' else '已暂停 · 确认键继续'
    else:
        message = '计时结束' if mode == 'done' else '已重置'
        draw.text((24, 105), message, font=ctx.font(46), fill='black', anchor='lt')
        footer = '在墨枢中开始下一轮'
        if mode == 'reset':
            ctx.state['timer'] = {}
    draw.line((24, 250, 376, 250), fill='black')
    draw.text((24, 268), footer, font=ctx.font(14), fill='black', anchor='lt')
    ctx.show(image)
