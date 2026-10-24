"""Original ZECTRIX geometry and accepted 400x300 layout, ported to Pillow.

See LICENSE and THIRD_PARTY_NOTICES.md. No screen transport lives here.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

PET = (
    '..###......###..', '..#..#....#..#..', '..#...####...#..',
    '.#............#.', '#..............#', '#..............#',
    '#..............#', '#..............#', '.#............#.',
    '..#..........#..', '...##########...', '....#......#....',
    '....#......#....', '...#........#...', '..############..',
    '..##........##..',
)
LABELS = {'working': '正在工作', 'waiting': '等你处理', 'done': '任务完成',
          'error': '遇到问题', 'stopped': '已停止', 'unknown': '状态待确认'}


def status(task):
    if not task:
        return None
    value = task['event']['status']
    return 'unknown' if task.get('stale') and value not in ('done', 'error', 'stopped') else value


def label(task):
    if status(task) == 'waiting' and task['event'].get('detail', '').startswith('权限审批'):
        return '等待权限审批'
    return LABELS.get(status(task), '等待任务')


def title_lines(value, width, maximum):
    lines, used = [''], 0
    for ch in value:
        w = 1 if ch.isascii() else 2
        if used + w > width:
            if len(lines) == maximum:
                lines[-1] = lines[-1][:-1] + '…'
                break
            lines.append('')
            used = 0
        lines[-1] += ch
        used += w
    return lines


def layout(model, frame=0, demo=None):
    task = model.current()
    if demo:
        task = dict(source='demo', stale=False, event=dict(
            task_id='demo', status=demo, title='整理今天的待办', detail='状态演示，不代表真实任务',
            progress=60 if demo == 'working' else None, agent='演示'))
    state = status(task)
    working = state == 'working'
    animate = working and model.settings['animation']
    phase = frame % 6 if animate else 0
    elements = []

    def text(content, x, y, size, width):
        elements.append(dict(type='text', content=content, x=x, y=y, size=size, width_limit=width))

    def rect(x, y, w, h, fill=None):
        e = dict(type='rect', x=x, y=y, w=w, h=h)
        if fill is not None:
            e['fill'] = fill
        elements.append(e)

    text('ZECTRIX / AGENT PET', 16, 19, 12, 260)
    text('演示' if demo else '实时', 341, 19, 12, 44)
    start = len(elements)
    active = model.running()
    if len(active) > 1 and not demo:
        pages = (len(active) + 3) // 4
        selected = model.state.get('selected')
        index = next((i for i, t in enumerate(active)
                      if f"{t['source']}:{t['event']['task_id']}" == selected), 0)
        page = index // 4
        text(f'{len(active)} 个任务' + (f' · {page+1}/{pages}' if pages > 1 else ''), 20, 112, 20, 224)
        row_height = {2: 62, 3: 45}.get(len(active), 36)
        for i, item in enumerate(active[page*4:page*4+4]):
            y = 143 + i * row_height
            text(''.join(title_lines(item['event']['title'], 24, 1)), 20, y, 17, 220)
            progress = item['event'].get('progress')
            text(label(item) + (f' · {progress}%' if progress is not None else ''), 20, y+16, 11, 220)
    else:
        text(label(task), 20, 116, 22, 224)
        title = task['event']['title'] if task else (
            'Codex 跟随已开启' if model.settings['codex_enabled'] else '本机 Codex 跟随已关闭')
        for i, line in enumerate(title_lines(title, 24, 3)):
            text(line, 20, 146+i*21, 18, 220)
        detail = task['event'].get('detail', '') if task else (
            '在本机 Codex 中开始一个任务' if model.settings['codex_enabled'] else '请开启跟随或接入 Agent')
        if task:
            if task.get('stale') and task['event']['status'] not in ('done', 'error', 'stopped'):
                detail = '一段时间未收到更新'
            elif detail.startswith('权限审批'):
                pass
            elif state == 'waiting':
                detail = '请回到 Codex / Agent 确认'
            elif state == 'done':
                detail = '本轮任务已结束'
        text(''.join(title_lines(detail, 30, 1)), 20, 213, 13, 220)
        progress = task['event'].get('progress') if task else None
        if progress is not None:
            rect(20, 228, 212, 13)
            if progress > 0:
                rect(23, 231, 206*progress//100, 7, 0)
            text(f'Agent 上报进度 {progress}%', 20, 258, 12, 218)
        elif working:
            text('进行中 · 未提供百分比', 20, 248, 12, 218)

    x, y, p = 254, 103, 7
    dx = (0, 1, 2, 1, 0, -1)[phase] if animate else 0
    for row, line in enumerate(PET):
        col = 0
        while col < len(line):
            if line[col] != '#':
                col += 1
                continue
            first = col
            while col < len(line) and line[col] == '#':
                col += 1
            rect(x + first*p + (dx if row <= 10 else 0), y + row*p, (col-first)*p-1, p-1, 0)
    if state == 'done':
        # Rasterize the original cheering strokes into rectangles, like the upstream renderer.
        mask = Image.new('1', (400, 300))
        d = ImageDraw.Draw(mask)
        for ex in (x+4*p, x+10*p):
            d.line([(ex, y+6*p), (ex+p, y+5*p), (ex+2*p, y+6*p)], fill=1, width=2)
        d.line([(x+6*p, y+8*p), (x+7*p, y+9*p), (x+9*p, y+9*p), (x+10*p, y+8*p)], fill=1, width=2)
        d.line([(x+3*p, y+12*p), (x-p, y+9*p)], fill=1, width=3)
        d.line([(x+13*p, y+12*p), (x+17*p, y+9*p)], fill=1, width=3)
        for xx, yy in ((x-7, y-10), (x+100, y-11), (x+115, y+30)):
            d.line([(xx, yy), (xx+7, yy+7)], fill=1, width=2)
            d.line([(xx+7, yy), (xx, yy+7)], fill=1, width=2)
        bbox = mask.getbbox()
        if bbox:
            for yy in range(bbox[1], bbox[3]):
                xx = bbox[0]
                while xx < bbox[2]:
                    if not mask.getpixel((xx, yy)):
                        xx += 1
                        continue
                    first = xx
                    while xx < bbox[2] and mask.getpixel((xx, yy)):
                        xx += 1
                    rect(first, yy, xx-first, 1, 0)
    else:
        for ex in (x+4*p+dx, x+10*p+dx):
            if state == 'error':
                rect(ex, y+5*p, p*2, 3, 0)
                rect(ex+p, y+5*p, 3, p*2, 0)
            else:
                rect(ex, y+5*p, p, 2 if phase == 3 else p*2, 0)
        rect(x+7*p+dx, y+8*p, p*2, p*2 if state == 'waiting' else p, 0)
    if working:
        rect(x+2*p, y+13*p, 12*p, 3*p, 255)
        rect(x+2*p, y+13*p, 12*p, 3*p)
        for col in range(4):
            rect(x+(4+2*col)*p, y+14*p, p, 1, 0)
        rect(285, 193 if phase % 2 == 0 else 185, 8, 7, 0)
        rect(327, 193 if phase % 2 == 1 else 185, 8, 7, 0)
    if state == 'done':
        text('完成！', 274, 246, 18, 105)
    if state in ('waiting', 'unknown'):
        text('?', 359, 99, 24, 20)
    for e in elements[start:]:
        e['y'] -= 16
    rect(16, 271, 368, 0)
    source = '本地运行'
    if task:
        source = {'demo': '演示数据', 'codex': 'Codex 本机'}.get(task['source'], task['event'].get('agent') or 'Agent 上报')
    text(source, 16, 285, 11, 143)
    text('上下翻页 · 确认首页' if len(active) > 4 and not demo else '上下选任务 · 确认跟随', 173, 285, 11, 212)
    return elements


def render(ctx, elements):
    image = Image.new('L', (400, 300), 255)
    draw = ImageDraw.Draw(image)
    fonts = {}
    for e in elements:
        x, y = e['x'], e['y']
        if e['type'] == 'rect':
            box = (x, y, x+max(e['w']-1, 0), y+max(e['h']-1, 0))
            if 'fill' in e:
                draw.rectangle(box, fill=e['fill'])
            else:
                draw.rectangle(box, outline=0)
        else:
            size, width = e['size'], e['width_limit']
            if size not in fonts:
                bold = Path('C:/Windows/Fonts/msyhbd.ttc')
                fonts[size] = ImageFont.truetype(str(bold), size) if size >= 24 and bold.exists() else ctx.font(size)
            font, content = fonts[size], e['content']
            layer = Image.new('L', (width, 80), 255)
            d = ImageDraw.Draw(layer)
            while content and d.textlength(content, font=font) > width:
                content = content[:-2] + '…' if len(content) > 2 else ''
            d.text((0, 48), content, font=font, fill=0, anchor='ls')
            image.paste(0, (x, y-48), ImageOps.invert(layer))
    return image
