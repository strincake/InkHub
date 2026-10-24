"""Loopback-only NOTE4 protocol simulator; no application or user data."""
import socket,struct,threading,time

class Peer:
    def __init__(self):
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.socket.bind(('127.0.0.1',0));self.socket.settimeout(.2)
        self.address=self.socket.getsockname();self.client=None;self.sid=0x1122334455667788
        self.image=0;self.bitmap=0;self.playback=0;self.begins=0;self.audio=0;self.closes=0;self.unknown=False;self.running=True;self.delay_until=0
        threading.Thread(target=self.run,daemon=True).start()
    def packet(self,kind,seq,body):return b'ZL\x01'+bytes([kind])+struct.pack('>QI',self.sid,seq)+body
    def run(self):
        while self.running:
            try:b,addr=self.socket.recvfrom(1201)
            except (TimeoutError,ConnectionResetError):continue
            except OSError:break
            if len(b)<16 or b[3]&128:continue
            kind=b[3];seq=int.from_bytes(b[12:16],'big');body=b'\0'
            if kind==1:body+=b'\0\x0c'+b'aabbccddeeff'+b'\x04test'+bytes([1,144,1,44,0,0,0,0,0,0,0,0])
            elif kind==2:self.client=addr;self.image=0;self.bitmap=0
            elif kind==16:body=bytes([0,0,85,170,255])+bytes(range(0,256,17))
            elif kind==5:
                if self.image!=seq:self.image=seq;self.bitmap=0;self.begins+=1
                if self.unknown:body=b'\x05'
            elif kind==6:self.bitmap|=1<<seq;continue
            elif kind==7:
                if time.monotonic()<self.delay_until:continue
                body+=bytes([3])+struct.pack('>Q',self.bitmap)
            elif kind==8:self.playback=seq;self.audio+=1
            elif kind==9:continue
            elif kind in (10,11):
                self.socket.sendto(self.packet(kind|128,seq,body),addr)
                self.socket.sendto(self.packet(13,100+seq,struct.pack('>I',self.playback)+bytes([2,0])),addr);self.playback=0;continue
            elif kind==12:body+=bytes([2,3,0 if not self.playback else 2])+struct.pack('>IQII',self.image,self.bitmap,self.playback,self.image)+b'\0'+struct.pack('>I',0)+b'\0'
            elif kind==4:self.closes+=1
            elif kind==15:body+=bytes([73,0,195])
            elif kind!=3:continue
            self.socket.sendto(self.packet(kind|128,seq,body),addr)
    def key(self,key,seq):self.socket.sendto(self.packet(14,seq,bytes([key,1])),self.client)
