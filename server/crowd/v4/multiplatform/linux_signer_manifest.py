"""Build a Linux Signer resource only from a pinned official wheel, not installed code.
The unchanged Signer wrapper validates this resource inside the new Linux bundle.
Mac resources are never edited. The caller must verify expected_wheel_sha against
the separately reviewed upstream uv.lock AND official registry provenance.
"""
import hashlib,io,stat,zipfile
from pathlib import PurePosixPath

def sha(raw):return hashlib.sha256(raw).hexdigest()
def generate(original,raw,expected_wheel_sha):
    if sha(raw)!=expected_wheel_sha:raise ValueError('wheel_hash_changed')
    result=[];proof=[]
    with zipfile.ZipFile(io.BytesIO(raw))as z:
        names=set()
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            if info.filename in names or p.is_absolute()or'..'in p.parts or stat.S_ISLNK(info.external_attr>>16)or info.file_size>4*1024*1024:raise ValueError('wheel_member_invalid')
            names.add(info.filename)
        for row in original:
            value=dict(row)
            if row['distribution']=='pycryptodome':
                if row['file']not in names:raise ValueError('wheel_member_missing')
                actual=sha(z.read(row['file']))
                if row['file'].endswith('.abi3.so'):
                    value['sha256']=actual;proof.append({'file':row['file'],'member_sha256':actual,'old_macos_sha256':row['sha256']})
                elif actual!=row['sha256']:raise ValueError('noncompiled_dependency_changed')
            result.append(value)
    if not proof:raise ValueError('compiled_dependency_missing')
    return result,{'wheel_sha256':expected_wheel_sha,'compiled_members':proof,'noncompiled_preserved':True}
