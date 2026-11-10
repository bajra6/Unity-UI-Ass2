"""Bake the CC0 GLB's first idle pose into an OBJ for Unity's built-in importer.
Run only when regenerating source art (requires numpy); runtime needs no Python packages.
Textures are extracted unchanged. Original GLB and source attribution are retained.
"""
import json, struct
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parents[1]
data = (root / 'ArtSource/person.glb').read_bytes()
length = struct.unpack_from('<I', data, 12)[0]
g = json.loads(data[20:20 + length])
binary = data[28 + length:]
out = root / 'Assets/GoodBoy/Art/Person'
out.mkdir(parents=True, exist_ok=True)

def acc(i):
    a = g['accessors'][i]; view = g['bufferViews'][a['bufferView']]
    dtype = {5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']]
    width = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
    item = np.dtype(dtype).itemsize
    value = np.ndarray((a['count'],width), dtype=dtype, buffer=binary,
        offset=view.get('byteOffset',0)+a.get('byteOffset',0),
        strides=(view.get('byteStride',item*width),item)).copy()
    if a.get('normalized'): value=value.astype(float)/np.iinfo(dtype).max
    return value

# Sample first authored pose (value is between in/out tangents for cubic interpolation).
for channel in g.get('animations',[{'channels':[]}])[0]['channels']:
    sampler = g['animations'][0]['samplers'][channel['sampler']]
    values = acc(sampler['output'])
    g['nodes'][channel['target']['node']][channel['target']['path']] = values[1 if sampler.get('interpolation')=='CUBICSPLINE' else 0].tolist()

def matrix(n):
    if 'matrix' in n:return np.array(n['matrix']).reshape(4,4).T
    x,y,z,w = n.get('rotation',[0,0,0,1])
    m=np.eye(4)
    m[:3,:3]=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])@np.diag(n.get('scale',[1,1,1]))
    m[:3,3]=n.get('translation',[0,0,0])
    return m
parents={child:i for i,n in enumerate(g['nodes']) for child in n.get('children',[])}
worlds={}
def world(i):
    if i not in worlds:worlds[i]=(world(parents[i]) if i in parents else np.eye(4))@matrix(g['nodes'][i])
    return worlds[i]

mtl=[]
for i,m in enumerate(g['materials']):
    p=m.get('pbrMetallicRoughness',{}); color=p.get('baseColorFactor',[1,1,1,1])
    mtl += [f'newmtl material_{i}', 'Kd '+' '.join(map(str,color[:3])), 'Ks 0.02 0.02 0.02', 'Ns 12']
    if 'baseColorTexture' in p:
        im=g['images'][g['textures'][p['baseColorTexture']['index']]['source']]
        view=g['bufferViews'][im['bufferView']]; ext='png' if im['mimeType']=='image/png' else 'jpg'
        name=f'texture_{i}.{ext}'; start=view.get('byteOffset',0)
        (out/name).write_bytes(binary[start:start+view['byteLength']])
        mtl += ['map_Kd '+name]
(out/'Owner.mtl').write_text('\n'.join(mtl))
with (out/'Owner.obj').open('w') as f:
    f.write('mtllib Owner.mtl\n'); offset=1
    for ni,n in enumerate(g['nodes']):
        if 'mesh' not in n or n.get('name')=='Briefcase':continue
        for pi,p in enumerate(g['meshes'][n['mesh']]['primitives']):
            attrs=p['attributes']; pos=acc(attrs['POSITION']); norm=acc(attrs['NORMAL'])
            if 'skin' in n:
                skin=g['skins'][n['skin']]; ibm=acc(skin['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
                matrices=np.array([world(j)@ibm[k] for k,j in enumerate(skin['joints'])])
                joints=acc(attrs['JOINTS_0']); weights=acc(attrs['WEIGHTS_0'])
                weights=weights/np.maximum(weights.sum(axis=1,keepdims=True),1e-9)
                blend=(matrices[joints]*weights[:,:,None,None]).sum(axis=1)
                pos=np.einsum('nij,nj->ni',blend,np.c_[pos,np.ones(len(pos))])[:,:3]
                norm=np.einsum('nij,nj->ni',blend[:,:3,:3],norm)
            else:
                pos=(np.c_[pos,np.ones(len(pos))]@world(ni).T)[:,:3]
                norm=norm@np.linalg.inv(world(ni)[:3,:3])
            norm/=np.maximum(np.linalg.norm(norm,axis=1,keepdims=True),1e-9)
            uv=acc(attrs['TEXCOORD_0']) if 'TEXCOORD_0' in attrs else np.zeros((len(pos),2))
            f.write(f'\ng mesh_{ni}_{pi}\nusemtl material_{p.get("material",0)}\n')
            for v in pos:f.write('v '+' '.join(f'{x:.7f}' for x in v)+'\n')
            for v in uv:f.write(f'vt {v[0]:.7f} {1-v[1]:.7f}\n')
            for v in norm:f.write('vn '+' '.join(f'{x:.7f}' for x in v)+'\n')
            indices=acc(p['indices']).flatten().reshape(-1,3)
            for tri in indices:
                f.write('f '+' '.join(f'{idx+offset}/{idx+offset}/{idx+offset}' for idx in tri)+'\n')
            offset+=len(pos)
print(f'Exported {offset-1} posed vertices to {out}')
