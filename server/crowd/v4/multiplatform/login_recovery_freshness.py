"""Safe content-access classification and post-failure login proof. No credentials."""
import math,time

def _time(value):
 return value if type(value) in (int,float) and math.isfinite(value) and value>0 else None

def failure_time(status):
 if not isinstance(status,dict) or status.get('state')!='login_required' or type(status.get('exit_code')) is not int or status['exit_code'] not in (77,78):return None
 return _time(status.get('updated_at'))

def recovery_newer_than_failure(state,account,failed_status=None,now=None):
 now=time.time() if now is None else now
 verified=_time(account.get('verified_at')) if isinstance(account,dict) else None
 if 'login_failed_at' in state:failed=_time(state['login_failed_at'])
 else:
  if not isinstance(failed_status,dict) or failed_status.get('run_id')!=state.get('local_run_id'):return False
  failed=failure_time(failed_status)
 return verified is not None and failed is not None and failed<verified<=now and 0<=now-verified<=180

def zhihu_content_denied(response):
 if type(getattr(response,'status_code',None)) is not int or response.status_code!=403:return False
 u=getattr(getattr(response,'request',None),'url',None)
 if u is None:return False
 return u.scheme=='https' and u.host in ('www.zhihu.com','zhihu.com','zhuanlan.zhihu.com') and u.path!='/api/v4/me'
