from datetime import date
from screen_plugin import ImageDraw

PAGE_SIZE = 5


def handle(ctx, event):
    items = list(dict.fromkeys(' '.join(line.split()) for line in ctx.settings['items'].splitlines()))
    items = [item for item in items if item][:24]
    today = date.today().isoformat()
    completed = set(ctx.state.get('completed', [])) if ctx.state.get('date') == today else set()
    index = ctx.state.get('index', 0) if ctx.state.get('date') == today else 0
    key = event.get('key')
    action = event.get('action')
    if event['type'] == 'key':
        action = {'Up': 'previous', 'Down': 'next', 'Confirm': 'toggle'}.get(key)
    if items:
        index = min(index, len(items) - 1)
        index = (index + {'previous': -1, 'next': 1}.get(action, 0)) % len(items)
        if action == 'toggle':
            completed.symmetric_difference_update({items[index]})
    else:
        index = 0
    new_state = {'date': today, 'items': items, 'completed': [item for item in items if item in completed], 'index': index}
    if event['type'] == 'interval' and new_state == ctx.state:
        return
    ctx.state.update(new_state)

    image = ctx.canvas()
    draw = ImageDraw.Draw(image)
    font = ctx.font(19)
    draw.text((24, 20), '今日清单', font=ctx.font(27), fill='black', anchor='lt')
    draw.text((376, 25), today, font=ctx.font(15), fill='black', anchor='rt')
    draw.line((24, 62, 376, 62), fill='black')
    page = index // PAGE_SIZE
    for offset, item in enumerate(items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]):
        y = 77 + offset * 34
        if offset == index % PAGE_SIZE:
            draw.polygon(((21, y + 5), (27, y + 11), (21, y + 17)), fill='black')
        draw.rectangle((37, y + 3, 52, y + 18), outline='black')
        if item in completed:
            draw.line((40, y + 10, 44, y + 14, 50, y + 5), fill='black', width=2)
        label = item[:120]
        if label != item or draw.textlength(label, font=font) > 302:
            while label and draw.textlength(label + '…', font=font) > 302:
                label = label[:-1]
            label += '…'
        draw.text((63, y), label, font=font, fill='black', anchor='lt')
    if not items:
        draw.text((24, 110), '请在插件设置中添加事项', font=font, fill='black', anchor='lt')
    draw.line((24, 252, 376, 252), fill='black')
    draw.text((24, 268), f"完成 {len(new_state['completed'])}/{len(items)}", font=ctx.font(15), fill='black', anchor='lt')
    draw.text((376, 268), f'{page+1}/{max(1, (len(items)+PAGE_SIZE-1)//PAGE_SIZE)} 页', font=ctx.font(15), fill='black', anchor='rt')
    ctx.show(image)
