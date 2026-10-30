"""Multi-note display; legacy settings stay readable until the first UI save."""
from screen_plugin import ImageDraw


def read_notes(settings):
    document = settings.get('document', {})
    if isinstance(document, dict) and document.get('version') == 2:
        items = document.get('notes', [])
        if not isinstance(items, list):
            raise ValueError('便签列表格式错误')
        return items
    texts = [line.strip() for line in settings.get('notes', '').splitlines() if line.strip()]
    return [dict(id=f'legacy-{i}', title=settings.get('title', ''), text=text,
                 show_title=True, font_size=24) for i, text in enumerate(texts or ['写下你的第一条便签。'])]


def wrap_text(text, measure, width=356):
    lines = []
    for paragraph in text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4).split('\n'):
        line = ''
        for char in paragraph:
            if line and measure(line + char) > width:
                lines.append(line)
                line = ''
            line += char
        lines.append(line)
    return lines


def shorten(text, measure, width=356):
    if measure(text) <= width:
        return text
    while text and measure(text + '…') > width:
        text = text[:-1]
    return text + '…'


def handle(ctx, event):
    notes = read_notes(ctx.settings)
    ids = [item['id'] for item in notes]
    selected = ctx.settings.get('active_note', '')
    current = ctx.state.get('current_note')
    if event['type'] == 'settings_changed' or current not in ids:
        current = selected if selected in ids else (ids[ctx.state.get('index', 0) % len(ids)] if ids else None)
    index = ids.index(current) if current in ids else 0
    if event.get('action') == 'next-note' or (event['type'] == 'key' and event.get('key') == 'Down'):
        index += 1
    if event['type'] == 'key' and event.get('key') == 'Up':
        index -= 1
    if event['type'] == 'key' and event.get('key') == 'Confirm':
        ctx.state['inverted'] = not ctx.state.get('inverted', False)
    if event.get('action') == 'reset':
        ctx.state.clear()
        index = 0
    index = index % len(notes) if notes else 0
    ctx.state.update(index=index, current_note=ids[index] if ids else None)
    dark = (ctx.settings.get('theme') == '深色') ^ ctx.state.get('inverted', False)
    background, foreground = ('black', 'white') if dark else ('white', 'black')
    image = ctx.canvas(background)
    draw = ImageDraw.Draw(image)
    if notes:
        note = notes[index]
        size = max(12, min(64, int(note.get('font_size', 24))))
        font = ctx.font(size)
        measure = lambda text: draw.textlength(text, font=font)
        top = 22
        if note.get('show_title', True):
            title_font = ctx.font(21)
            title = shorten(note.get('title', '').replace('\n', ' '), lambda t: draw.textlength(t, font=title_font))
            draw.text((22, 20), title, font=title_font, fill=foreground, anchor='lt')
            draw.line((22, 60, 378, 60), fill=foreground)
            top = 82
        line_height = int(size * 1.45 + 0.5)
        limit = max(1, (278 - top) // line_height)
        lines = wrap_text(note.get('text', ''), measure)
        visible = lines[:limit]
        if len(lines) > limit:
            visible[-1] = shorten(visible[-1] + '…', measure)
        for row, line in enumerate(visible):
            draw.text((22, top + row * line_height), line, font=font, fill=foreground, anchor='lt')
    ctx.show(image, 'mono')
    ctx.trigger_after(ctx.settings.get('refresh_seconds', 30))
