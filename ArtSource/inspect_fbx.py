import struct, zlib
from pathlib import Path
b = Path(__file__).with_name('dog.fbx').read_bytes()
def prop(p):
    t=chr(b[p]); p+=1
    if t in 'YCFDI L'.replace(' ',''):
        f={'Y':'h','C':'?','F':'f','D':'d','I':'i','L':'q'}[t]
        return struct.unpack_from('<'+f,b,p)[0],p+struct.calcsize(f)
    if t in 'SR':
        n=struct.unpack_from('<I',b,p)[0];p+=4
        v=b[p:p+n]
        return (v.decode(errors='replace') if t=='S' else v),p+n
    n,enc,size=struct.unpack_from('<III',b,p);p+=12
    return ('array',t,n),p+size
def node(p):
    end,n,l,ns=struct.unpack_from('<IIIB',b,p);p+=13
    if not end:return None,p
    name=b[p:p+ns].decode();p+=ns;v=[]
    for _ in range(n):
        x,p=prop(p);v.append(x)
    kids=[]
    while p<end-13:
        c,p=node(p)
        if c:kids.append(c)
    return (name,v,kids),end
p=27
while p<len(b):
    n,p=node(p)
    if not n:break
    if n[0]=='Objects':
        for k,v,cs in n[2]:
            if k in ('Model','Material'):
                print(k,v)
                for ck,cv,cc in cs:
                    if ck=='Properties70':
                        for pk,pv,pc in cc:
                            if pv[0] in ('Lcl Translation','Lcl Rotation','Lcl Scaling','DiffuseColor'):print('  ',pv)
