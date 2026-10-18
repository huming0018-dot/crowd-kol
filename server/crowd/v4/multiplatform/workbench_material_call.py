"""Command contract for existing dashboard/AnalysisJobs worker, not a scheduler."""
from pathlib import Path
import hashlib,os,stat,re
KEYS={'python','script','script_sha256','request','request_sha256'}

def _digest(path,limit=1024*1024):
 path=Path(path)
 if not path.is_absolute()or any(p.is_symlink()for p in (path,*path.parents)):raise ValueError('material_config_unsafe')
 try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 except OSError:raise ValueError('material_config_unsafe')from None
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode)or before.st_nlink!=1 or before.st_size>limit:raise ValueError('material_config_unsafe')
  blob=os.read(fd,limit+1);after=os.fstat(fd)
  if len(blob)!=before.st_size or (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('material_config_changed')
  return hashlib.sha256(blob).hexdigest()
 except OSError:raise ValueError('material_config_unsafe')from None
 finally:os.close(fd)

def command(config,action='read',fmt='html'):
 if type(config)is not dict or set(config)!=KEYS or any(type(v)is not str for v in config.values())or action not in ('build','read','pack-info')or fmt not in ('html','json','jsonl','csv'):raise ValueError('material_config_invalid')
 if any(re.fullmatch('[a-f0-9]{64}',config[n])is None for n in ('script_sha256','request_sha256')):raise ValueError('material_config_invalid')
 # Normal venv interpreter symlinks retain their original invocation spelling.
 python=Path(config['python'])
 if not python.is_absolute()or not python.is_file()or not os.access(python,os.X_OK):raise ValueError('material_python_unavailable')
 for name in ('script','request'):
  if _digest(config[name])!=config[name+'_sha256']:raise ValueError('material_config_changed')
 # Caller owns these protected files across validation and process creation.
 return [str(python),'-B',config['script'],'--request',config['request'],'--action',action,'--format',fmt]
