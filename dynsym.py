import struct,sys
f=open(sys.argv[1],'rb'); d=f.read()
assert d[:4]==b'\x7fELF'
is64=d[4]==2; le=d[5]==1
end='<' if le else '>'
def U(fmt,o): return struct.unpack_from(end+fmt,d,o)
e_shoff=U('Q',0x28)[0]; e_shentsize=U('H',0x3a)[0]; e_shnum=U('H',0x3c)[0]; e_shstrndx=U('H',0x3e)[0]
secs=[]
for i in range(e_shnum):
    b=e_shoff+i*e_shentsize
    name,typ,flags,addr,off,size,link,info,align,entsize=U('IIQQQQIIQQ',b)
    secs.append(dict(name=name,typ=typ,off=off,size=size,link=link,entsize=entsize))
shstr=secs[e_shstrndx]
def sname(n): 
    e=d.index(b'\x00',shstr['off']+n); return d[shstr['off']+n:e].decode('latin1')
dynsym=None;dynstr=None
for s in secs:
    nm=sname(s['name'])
    if nm=='.dynsym': dynsym=s
    if nm=='.dynstr': dynstr=s
if not dynsym:
    print("no .dynsym"); sys.exit()
def strat(o):
    e=d.index(b'\x00',dynstr['off']+o); return d[dynstr['off']+o:e].decode('latin1')
cnt=dynsym['size']//dynsym['entsize']
names=[]
for i in range(cnt):
    b=dynsym['off']+i*dynsym['entsize']
    st_name,st_info,st_other,st_shndx,st_value,st_size=U('IBBHQQ',b)
    nm=strat(st_name)
    if nm: names.append((nm,st_shndx))
import re
pat=re.compile(sys.argv[2]) if len(sys.argv)>2 else None
tot=len(names)
sel=[n for n,sh in names if pat and pat.search(n)]
print("total dynsym:",tot)
print("matches:",len(sel))
for n in sorted(set(sel))[:120]:
    print("  ",n)
