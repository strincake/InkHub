"""Standard-library HTTP client. Success means accepted, not physical display."""
from dataclasses import dataclass
from enum import Enum
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import json
import os
import threading
import time

class ImageFormat(str, Enum):
    Mono="mono"
    Gray4="gray4"
    Gray16="gray16"

@dataclass
class OpenOptions:
    target: str="http://127.0.0.1:38477"
    client_name: str="HTTP 图片来源"

class SchedulerError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status=status

class Device:
    @classmethod
    def open(cls, options=None, api_key=None):
        return cls(options or OpenOptions(), api_key or os.environ.get("SCREEN_SCHEDULER_KEY", ""))

    def __init__(self, options, api_key):
        base=options.target.rstrip("/")
        if not base.startswith("http://"):
            base="http://"+base
        from urllib.parse import urlsplit
        parsed=urlsplit(base)
        if parsed.scheme!="http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("请输入调度台 HTTP 地址")
        if parsed.port is None:
            base=f"http://{parsed.hostname}:38477"
        self._base=base
        self._opener=build_opener(ProxyHandler({}))
        self._token=api_key
        session=self._request("POST", "/v1/sessions", {"name":options.client_name})
        self.id=session["id"]
        self._token=session["token"]
        self._path="/v1/sessions/"+self.id
        self._seq=0
        self._sequence_lock=threading.Lock()
        self._event_lock=threading.Lock()
        self._cursor=0
        self._stop=threading.Event()
        self._closed=False
        self._heart=threading.Thread(target=self._heartbeat, daemon=True)
        self._heart.start()

    def _request(self, method, path, body=None, headers=None):
        headers=dict(headers or {})
        headers["Authorization"]="Bearer "+self._token
        if isinstance(body,dict):
            body=json.dumps(body).encode()
            headers["Content-Type"]="application/json"
        try:
            with self._opener.open(Request(self._base+path,data=body,headers=headers,method=method),timeout=8) as response:
                return json.load(response)
        except HTTPError as error:
            raise SchedulerError(error.code,error.read().decode("utf-8",errors="replace")) from error

    def _heartbeat(self):
        while not self._stop.wait(5):
            try:
                self._request("POST",self._path+"/heartbeat")
            except Exception:
                self._closed=True
                self._stop.set()

    @property
    def last_sequence(self):
        return self._seq

    def show(self, png):
        self.show_with_format(png,ImageFormat.Mono)

    def show_with_format(self, png, image_format):
        self.submit(png,image_format)

    def submit(self,png,image_format=ImageFormat.Mono,sequence=None):
        if self._closed:
            raise SchedulerError(401,"来源连接已结束，请显式重新连接")
        with self._sequence_lock:
            sequence=self._seq+1 if sequence is None else sequence
            self._seq=max(sequence,self._seq)
        return self._request("POST",f"{self._path}/frames/{sequence}",png,{"Content-Type":"image/png","x-image-format":ImageFormat(image_format).value})

    def receipt(self,sequence):
        return self._request("GET",f"{self._path}/frames/{sequence}")

    def next_event(self,timeout=None):
        with self._event_lock:
            deadline=None if timeout is None else time.monotonic()+timeout
            while not self._closed:
                result=self._request("GET",f"{self._path}/events?after={self._cursor}")
                if result["gap"]:
                    self._cursor=result["cursor"]
                    raise SchedulerError(409,"按键处理过慢，部分旧事件已移除")
                if result["events"]:
                    event=result["events"][0]
                    self._cursor=event["cursor"]
                    return event
                if deadline is not None and time.monotonic()>=deadline:
                    return None
                self._stop.wait(.2)
            return None

    def close(self):
        if self._closed:
            return
        self._closed=True
        self._stop.set()
        try:
            self._request("DELETE",self._path)
        except SchedulerError as error:
            if error.status not in (401,404):
                raise

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
