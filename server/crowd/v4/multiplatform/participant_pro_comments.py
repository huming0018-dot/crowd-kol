"""Pure typed saved Pro comments. No collector, parser, credentials or queue."""
import hashlib,json,re,uuid
from datetime import datetime,timedelta
PAYLOAD_LIMIT=131072
COMMENT='crowd-participant-pro-comment-v1'
CAPTURE='crowd-participant-pro-comment-capture-v1'
PROVENANCE={'local_run_id','upstream_commit','observation_sha256','request_sha256','captured_at'}
RECEIPT={'request','gate','inserted','duplicate','parent_request','note_id','comment_id','record_hash','source_kind','reward_eligible','created_at'}
class CommentError(ValueError):pass
def need(ok):
 if not ok:raise CommentError('participant_comment_contract_invalid')
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def uid(v):
 try:need(type(v)is str and str(uuid.UUID(v))==v)
 except (ValueError,TypeError,AttributeError):raise CommentError('participant_comment_contract_invalid')from None
 return v
def hexid(v):return type(v)is str and re.fullmatch('[a-f0-9]{24}',v)is not None
def hexsha(v):return type(v)is str and re.fullmatch('[a-f0-9]{64}',v)is not None
def stamp(v):
 try:need(type(v)is str and datetime.fromisoformat(v.replace('Z','+00:00')).utcoffset()==timedelta(0))
 except (ValueError,AttributeError,TypeError):raise CommentError('participant_comment_contract_invalid')from None
 return v
def options(v):
 need(type(v)is dict and set(v)=={'comments','replies','max_comments'}and type(v['comments'])is bool and type(v['replies'])is bool and type(v['max_comments'])is int and v['max_comments']>=0 and (v['comments']or not v['replies']));return v
def request_id(run,task,note,comment=None):
 uid(run);need(type(task)is int and task>0 and hexid(note)and(comment is None or hexid(comment)))
 return str(uuid.uuid5(uuid.UUID(run),str(task)+(':comment-capture:'+note if comment is None else ':comment:'+note+':'+comment)))
def body_request(run,task,note):return str(uuid.uuid5(uuid.UUID(uid(run)),str(task)+':'+note))
def validate_payload(p,task,parent):
 uid(parent);need(type(task)is int and task>0)
 need(type(p)is dict and set(p)=={'schema','source_kind','reward_eligible','record','canonical_record','provenance'}and p['schema']in(COMMENT,CAPTURE)and p['source_kind']=='mediacrawler_pro'and p['reward_eligible']is False and len(canonical(p).encode())<=PAYLOAD_LIMIT)
 r=p['record'];pv=p['provenance'];need(type(r)is dict and type(pv)is dict and set(pv)==PROVENANCE)
 run=uid(pv['local_run_id']);stamp(pv['captured_at']);need(type(pv['upstream_commit'])is str and re.fullmatch('[a-f0-9]{40}',pv['upstream_commit'])and hexsha(pv['request_sha256']))
 need(r.get('platform')=='xiaohongshu'and r.get('reward_eligible')is False and hexid(r.get('content_id'))and r.get('origin',{}).get('run_id')==run)
 unsigned={k:v for k,v in r.items()if k!='record_hash'};need(p['canonical_record']==canonical(unsigned)and r.get('record_hash')==sha(unsigned)and pv['observation_sha256']==r['record_hash']and parent==body_request(run,task,r['content_id']))
 if p['schema']==COMMENT:
  need(r.get('kind')=='comment'and r.get('source_kind')=='mediacrawler_api'and hexid(r.get('comment_id'))and(r.get('parent_comment_id')==''or hexid(r.get('parent_comment_id'))))
  need(type(r.get('text'))is str and r.get('text_status')=='reported'and r.get('text_truncated')is False)
 else:
  need(set(r)=={'kind','platform','content_id','source_kind','reward_eligible','origin','objects','pages','source_pagination_sha256','coverage','resolved_native_options','record_hash'})
  need(r['kind']=='comment_capture'and r['source_kind']=='mediacrawler_pro_manifest'and type(r['origin'])is dict and set(r['origin'])=={'run_id'}and (hexsha(r['source_pagination_sha256']) or r['source_pagination_sha256'] is None))
  opts=options(r['resolved_native_options']);need(opts['comments']is True)
  need(type(r['objects'])is list and len(r['objects'])<=10000 and type(r['pages'])is list and len(r['pages'])<=1000)
  seen=set();ids=set()
  for x in r['objects']:
   need(type(x)is dict and set(x)=={'request','comment_id','record_hash'}and hexid(x['comment_id'])and hexsha(x['record_hash'])and x['request']==request_id(run,task,r['content_id'],x['comment_id'])and x['request']not in seen and x['comment_id']not in ids);seen.add(x['request']);ids.add(x['comment_id'])
  cov=r['coverage'];need(type(cov)is dict and set(cov)=={'coverage','reason'}and cov['coverage']in('exhausted','limit_reached','partial','unknown')and type(cov['reason'])is str and re.fullmatch('[a-z_]{1,100}',cov['reason']))
  pageids=set();savedids=set();roots=[]
  for page in r['pages']:
   need(type(page)is dict and page.get('scope')in('root','reply')and page.get('content_id')==r['content_id']and type(page.get('ids'))is list and all(hexid(i)for i in page['ids'])and len(page['ids'])==len(set(page['ids'])))
   need(all(type(page.get(k))is bool for k in ['has_more','saved','checkpoint_committed','embedded','invalid'])and page['invalid']is False)
   need(page.get('parent_id')is None if page['scope']=='root'else hexid(page.get('parent_id')))
   need(type(page.get('cursor_out'))is str and len(page['cursor_out'])<=512 and(page['embedded']and page.get('cursor_in')is None or type(page.get('cursor_in'))is str and len(page['cursor_in'])<=512))
   if page['scope']=='root':roots.append(page)
   else:need(opts['replies']is True)
   pageids.update(page['ids'])
   if page['saved']:savedids.update(page['ids'])
  need(savedids<=ids<=pageids)
  if cov['coverage'] in ('exhausted','limit_reached'):need(all(p['saved'] for p in r['pages']) and pageids==ids)
  if not roots:need(not ids and not r['pages'] and cov['coverage'] in ('partial','unknown') and r['source_pagination_sha256'] is None)
  else:need(hexsha(r['source_pagination_sha256']))
  if cov['coverage']=='exhausted':
   need(roots and roots[0]['cursor_in']=='' and roots[-1]['has_more']is False and all(x['checkpoint_committed']is True for x in roots))
   seenroots=set();seen_cursors=set()
   for i,page in enumerate(roots):
    need(page['cursor_in'] not in seen_cursors and not(seenroots & set(page['ids'])))
    if i:need(roots[i-1]['has_more'] and roots[i-1]['cursor_out']==page['cursor_in'])
    seen_cursors.add(page['cursor_in']);seenroots.update(page['ids'])
    need(type(page.get('reply_roots')) is dict and set(page['reply_roots'])==set(page['ids']) and all(type(n)is int and n>=0 for n in page['reply_roots'].values()))
    if opts['replies']:
     need(type(page.get('reply_cursor_start'))is dict)
     for parent,count in page['reply_roots'].items():
      replies=[p for p in r['pages'] if p['scope']=='reply' and p['parent_id']==parent]
      allids=[cid for p in replies for cid in p['ids']]
      need((count==0 and not replies) or (count>0 and replies and not replies[-1]['has_more'] and len(set(allids))==len(allids)==count))
      for j,reply in enumerate(replies):
       if j:need(replies[j-1]['has_more'] and replies[j-1]['cursor_out']==reply['cursor_in'])
       elif not reply['embedded']:need(reply['cursor_in']==page['reply_cursor_start'].get(parent))
   need(all(p['parent_id'] in seenroots for p in r['pages'] if p['scope']=='reply'))
 return r

def payload(record,provenance,schema=COMMENT):
 return {'schema':schema,'source_kind':'mediacrawler_pro','reward_eligible':False,'record':record,'canonical_record':canonical({k:v for k,v in record.items()if k!='record_hash'}),'provenance':{**provenance,'observation_sha256':record['record_hash']}}

def capture_payload(note,comments,pages,pages_sha,coverage,provenance,task,resolved):
 need(hexid(note)and type(comments)is list and type(pages)is list)
 byid={r['comment_id']:r for r in comments};need(len(byid)==len(comments))
 for r in comments:
  need(r['content_id']==note)
  visited={r['comment_id']};parent=r.get('parent_comment_id')
  while parent!='':
   need(parent in byid and parent not in visited);visited.add(parent);parent=byid[parent].get('parent_comment_id')
 for page in pages:
  for cid in page.get('ids',[]):
   if cid in byid:need(byid[cid].get('parent_comment_id')==(''if page.get('scope')=='root'else page.get('parent_id')))
 run=provenance['local_run_id'];rec={'kind':'comment_capture','platform':'xiaohongshu','content_id':note,'source_kind':'mediacrawler_pro_manifest','reward_eligible':False,'origin':{'run_id':run},'objects':[{'request':request_id(run,task,note,r['comment_id']),'comment_id':r['comment_id'],'record_hash':r['record_hash']}for r in sorted(comments,key=lambda r:r['comment_id'])],'pages':pages,'source_pagination_sha256':pages_sha,'coverage':coverage,'resolved_native_options':options(resolved)}
 rec['record_hash']=sha(rec);p=payload(rec,provenance,CAPTURE);validate_payload(p,task,body_request(run,task,note));return p

def validate_receipt(result,request,p,parent):
 need(type(result)is dict and set(result)==RECEIPT);r=p['record'];capture=p['schema']==CAPTURE
 need(result['request']==request and result['gate']==('comment_capture_received'if capture else'comment_received')and result['parent_request']==parent and result['note_id']==r['content_id']and result['comment_id']==(None if capture else r['comment_id'])and result['record_hash']==r['record_hash']and result['source_kind']=='mediacrawler_pro'and result['reward_eligible']is False and type(result['inserted'])is bool and type(result['duplicate'])is bool and result['inserted']!=result['duplicate']);stamp(result['created_at']);return result

def validate_children(bodies,rows,captures,task):
 need(type(rows)is list and type(captures)is list and len(rows)<=10000 and len(captures)<=2000)
 parents={x['request']:x for x in bodies};seen=set();byparent={};seals={}
 for row in rows+captures:
  need(type(row)is dict and set(row)=={'request','parent_request','created_at','pro_payload','receipt'})
  parent=row['parent_request'];need(parent in parents);uid(row['request']);stamp(row['created_at']);p=row['pro_payload'];r=validate_payload(p,task,parent);body=parents[parent]['pro_payload']
  need(r['content_id']==body['record']['content_id']and {k:v for k,v in p['provenance'].items()if k!='observation_sha256'}=={k:v for k,v in body['provenance'].items()if k!='observation_sha256'})
  iscap=p['schema']==CAPTURE;need((row in captures)==iscap and row['request']==request_id(p['provenance']['local_run_id'],task,r['content_id'],None if iscap else r['comment_id'])and row['request']not in seen);seen.add(row['request'])
  receipt=validate_receipt(row['receipt'],row['request'],p,parent);need(datetime.fromisoformat(receipt['created_at'].replace('Z','+00:00'))==datetime.fromisoformat(row['created_at'].replace('Z','+00:00')))
  if iscap:need(parent not in seals);seals[parent]=row
  else:byparent.setdefault(parent,[]).append(row)
 for parent,seal in seals.items():
  got={x['request']:(x['pro_payload']['record']['comment_id'],x['pro_payload']['record']['record_hash'])for x in byparent.get(parent,[])};expected={x['request']:(x['comment_id'],x['record_hash'])for x in seal['pro_payload']['record']['objects']};need(got==expected)
  r=seal['pro_payload']['record'];capture_payload(r['content_id'],[x['pro_payload']['record']for x in byparent.get(parent,[])],r['pages'],r['source_pagination_sha256'],r['coverage'],{k:v for k,v in seal['pro_payload']['provenance'].items()if k!='observation_sha256'},task,r['resolved_native_options'])
 need(set(byparent)<=set(seals));return {parent:{'comment_receipts':sorted(byparent.get(parent,[]),key=lambda x:x['request']),'comment_capture':seals.get(parent)}for parent in parents}
