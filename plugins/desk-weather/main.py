from urllib.parse import urlencode
from screen_plugin import ImageDraw

CONDITIONS = {
    0: '晴', 1: '少云', 2: '多云', 3: '阴', 45: '雾', 48: '雾凇',
    51: '小毛毛雨', 53: '毛毛雨', 55: '强毛毛雨', 56: '冻毛毛雨', 57: '冻毛毛雨',
    61: '小雨', 63: '中雨', 65: '大雨', 66: '冻雨', 67: '冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒', 80: '小阵雨', 81: '阵雨',
    82: '强阵雨', 85: '阵雪', 86: '强阵雪', 95: '雷雨', 96: '雷雨伴冰雹', 99: '雷雨伴冰雹',
}


def get_forecast(ctx, coordinates):
    latitude, longitude = coordinates
    query = urlencode({
        'latitude': latitude, 'longitude': longitude, 'timezone': 'auto', 'forecast_days': 1,
        'current': 'temperature_2m,weather_code',
        'daily': 'temperature_2m_min,temperature_2m_max,precipitation_probability_max',
    })
    data = ctx.fetch_json('https://api.open-meteo.com/v1/forecast?' + query, timeout=5)
    current, daily = data['current'], data['daily']
    return {
        'temperature': round(current['temperature_2m']),
        'condition': CONDITIONS.get(current['weather_code'], '天气未知'),
        'low': round(daily['temperature_2m_min'][0]),
        'high': round(daily['temperature_2m_max'][0]),
        'rain': daily['precipitation_probability_max'][0],
        'time': current['time'][:16].replace('T', ' '),
    }


def handle(ctx, event):
    coordinates = [ctx.settings['latitude'], ctx.settings['longitude']]
    if ctx.state.get('coordinates') != coordinates:
        ctx.state.clear()
        ctx.state['coordinates'] = coordinates
    if event['type'] != 'display_settings_changed' or 'forecast' not in ctx.state:
        try:
            ctx.state['forecast'] = get_forecast(ctx, coordinates)
            ctx.state['offline'] = False
        except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError):
            ctx.state['offline'] = True
    ctx.trigger_after(round(ctx.settings['refresh_minutes'] * 60))

    image = ctx.canvas()
    draw = ImageDraw.Draw(image)
    place = ' '.join(ctx.settings['place'].split())[:12] or '桌面天气'
    draw.text((24, 20), place, font=ctx.font(24), fill='black', anchor='lt')
    forecast = ctx.state.get('forecast')
    if forecast:
        draw.text((24, 66), f"{forecast['temperature']}°", font=ctx.font(82), fill='black', anchor='lt')
        draw.text((24, 157), forecast['condition'], font=ctx.font(22), fill='black', anchor='lt')
        draw.line((24, 198, 376, 198), fill='black')
        rain = forecast['rain']
        rain_label = f'{rain}%' if isinstance(rain, (int, float)) else '未知'
        detail = f"最高 {forecast['high']}°  最低 {forecast['low']}°  降水 {rain_label}"
        draw.text((24, 216), detail, font=ctx.font(16), fill='black', anchor='lt')
        prefix = '缓存' if ctx.state['offline'] else '预报时刻'
        footer = f"{prefix} {forecast['time']} · Open-Meteo"
    else:
        draw.text((24, 112), '天气暂不可用', font=ctx.font(25), fill='black', anchor='lt')
        draw.text((24, 159), '请检查网络或地点坐标', font=ctx.font(18), fill='black', anchor='lt')
        footer = 'Open-Meteo'
    draw.text((24, 268), footer, font=ctx.font(13), fill='black', anchor='lt')
    ctx.show(image)
