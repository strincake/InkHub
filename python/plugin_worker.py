"""One plugin event per subprocess. Only the final result goes to stdout."""
import importlib.util,io,json,sys,asyncio,inspect,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'plugin_kit'))
from screen_plugin import Context
class LogBuffer(io.TextIOBase):
    def __init__(self):self.value=''
    def write(self,value):self.value=(self.value+str(value))[-8000:];return len(value)
    def flush(self):pass
def main():
    request=json.load(sys.stdin);package=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve();data=Path(sys.argv[3]).resolve()
    log=LogBuffer();original=sys.stdout;sys.stdout=log
    try:
        sys.path.insert(0,str(package))
        entry=(package/request['entry']).resolve()
        if not entry.is_relative_to(package):raise ValueError('插件入口越界')
        spec=importlib.util.spec_from_file_location('screen_plugin_entry',entry);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        ctx=Context(request,package,data,output);result=module.handle(ctx,request['event'])
        if inspect.isawaitable(result):asyncio.run(result)
        state=json.dumps(ctx.state,ensure_ascii=False)
        if len(state.encode())>65536:raise ValueError('插件状态最多 64 KiB')
        if ctx._shown and output.stat().st_size>8*1024*1024:raise ValueError('输出 PNG 超过 8 MiB')
        channels=[]
        for key,c in ctx._channels.items():
            if c._shown and c._output.stat().st_size>8*1024*1024:raise ValueError('通道图片超过 8 MiB')
            channels.append({'key':key,'name':c._name,'rules':c._rules,'shown':c._shown,'format':c._format,'require_visible':c._require_visible})
        result={'channels':channels,'state':ctx.state,'shown':ctx._shown,'format':ctx._format,'after_seconds':ctx._after,'log':log.value,'require_visible':ctx._require_visible,'audio':ctx._audio}
        original.write(json.dumps(result,ensure_ascii=False));original.flush()
    except Exception:
        sys.stderr.write(traceback.format_exc()[-8000:]);sys.exit(1)
if __name__=='__main__':main()
