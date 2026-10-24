"""Plugin author API. Plugin code is trusted local Python, not sandboxed."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json,urllib.request,io,wave

class Context:
    def __init__(self,request,package_dir,data_dir,output):
        self.settings=request['settings'];self.state=request['state'];self.package_dir=Path(package_dir);self.data_dir=Path(data_dir)
        self.display=request.get('display',{'visible':False,'format':'mono','fit':'contain'})
        self.data_dir.mkdir(parents=True,exist_ok=True);self._output=Path(output);self._format='mono';self._shown=False;self._after=None
        self._require_visible=False;self._audio=None;self._channels={};self._request=request
    def register_channel(self,key,name,rules=None):
        """Declare every active channel on each event; omitted channels are withdrawn."""
        import re
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',key):raise ValueError('通道 ID 格式错误')
        if key in self._channels or len(self._channels)>=32:raise ValueError('通道重复或超过 32 个')
        if not isinstance(name,str) or not name.strip() or len(name)>40:raise ValueError('通道名称应为 1～40 字')
        request={'settings':self.settings,'state':{},'display':self._request.get('channels',{}).get(key,{'visible':False,'now':self.display.get('now',0)})}
        channel=Context(request,self.package_dir,self.data_dir,self._output.with_name('channel-'+key+'.png'))
        channel._key=key;channel._name=name;channel._rules=rules or {}
        self._channels[key]=channel
        return channel
    def require_visible(self):
        """Discard this event's state and image if its displayed frame loses ownership before commit."""
        self._require_visible=True
    def canvas(self,color='white'):
        return Image.new('RGB',(400,300),color)
    def font(self,size=24):
        for path in ('C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/segoeui.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
            if Path(path).exists():return ImageFont.truetype(path,size)
        return ImageFont.load_default()
    def show(self,image,format='mono'):
        if format not in ('mono','gray4','gray16'):raise ValueError('format 应为 mono / gray4 / gray16')
        if not isinstance(image,Image.Image):
            with Image.open(image) as file:image=file.copy()
        if image.size!=(400,300):raise ValueError('插件必须提交 400×300 图片；缩放和裁剪请在插件内完成')
        image.save(self._output,format='PNG');self._format=format;self._shown=True
    def play_wav(self,wav_bytes_or_path,volume=90):
        """Submit one short device sound, bound to this event's displayed or new frame."""
        if self._audio is not None:raise ValueError('每次事件最多一个声音请求')
        if isinstance(volume,bool) or not isinstance(volume,int) or not 0<=volume<=100:raise ValueError('音量应为 0～100 的整数')
        if isinstance(wav_bytes_or_path,(bytes,bytearray,memoryview)):raw=bytes(wav_bytes_or_path)
        else:
            with Path(wav_bytes_or_path).open('rb') as f:raw=f.read(98305)
        if len(raw)>98304:raise ValueError('WAV 最多 96 KiB')
        with wave.open(io.BytesIO(raw),'rb') as wav:
            if (wav.getnchannels(),wav.getframerate(),wav.getsampwidth(),wav.getcomptype())!=(1,16000,2,'NONE'):raise ValueError('WAV 必须为 16 kHz 单声道 PCM16')
            frames=wav.getnframes()
            if not 0<frames<=48000 or len(wav.readframes(frames))!=frames*2:raise ValueError('WAV 必须完整且时长为 0～3 秒')
        self._output.with_suffix('.wav').write_bytes(raw)
        self._audio={'path':'frame.wav','volume':volume}
    def trigger_after(self,seconds):
        if not isinstance(seconds,(int,float)) or not 1<=seconds<=86400:raise ValueError('再次触发应为 1～86400 秒')
        self._after=seconds
    def fetch_json(self,url,timeout=5,headers=None):
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=min(timeout,10)) as response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('JSON 响应超过 1 MiB')
            return json.loads(raw)

__all__=['Context','Image','ImageDraw','ImageFont']
