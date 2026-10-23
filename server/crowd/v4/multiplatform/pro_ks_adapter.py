"""Own saved-evidence boundary; upstream handles every platform request/extraction/store."""
import collections,copy,hashlib,json

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()

def saved_matches(row,expected):
 # Original SQLite declares only create_time INTEGER while native model uses string.
 return all(row.get(k)==v or k=='create_time' and type(row.get(k))is int and isinstance(v,str) and v.isdecimal() and str(row[k])==v for k,v in expected.items())

class Evidence:
 def __init__(self,video_id):self.video_id=video_id;self.detail=None;self.pages=[];self.errors=[]
 def detail_response(self,raw):self.detail=copy.deepcopy(raw)
 def page(self,kind,cursor,raw,parent=None):
  if kind not in ('root','reply'):raise ValueError('ks_page_kind')
  self.pages.append({'kind':kind,'cursor':cursor,'parent':parent,'raw':copy.deepcopy(raw),'sha256':digest(raw)})
 def failed(self,kind,cursor):self.errors.append({'kind':kind,'cursor':cursor})
 def project(self,videos,comments,run_id):
  from media_platform.kuaishou.extractor import KuaishouExtractor
  import mc_runner
  if self.errors or len(videos)!=1 or self.detail is None:raise ValueError('ks_capture_unknown')
  extractor=KuaishouExtractor();native=extractor.extract_video_from_dict(self.detail.get('visionVideoDetail'))
  if native is None or native.video_id!=self.video_id:raise ValueError('ks_content_binding')
  if not saved_matches(videos[0],native.model_dump()):raise ValueError('ks_saved_content_changed')
  chains={};expected={};parents={};subcounts={};declared_counts={}
  for page in self.pages:
   raw=page['raw'];kind=page['kind'];parent=page['parent'];key=(kind,parent)
   if page['sha256']!=digest(raw) or type(raw)is not dict:raise ValueError('ks_page_changed')
   rowskey='rootCommentsV2'if kind=='root'else'subCommentsV2'
   if type(raw.get(rowskey))is not list or not isinstance(raw.get('pcursorV2'),str) or not raw['pcursorV2']:raise ValueError('ks_page_terminal_unverified')
   wanted=chains.get(key,'')
   if wanted=='no_more' or page['cursor']!=wanted:raise ValueError('ks_page_cursor_or_replay')
   chains[key]=raw['pcursorV2']
   models=extractor.extract_comments_from_list_v2(self.video_id,raw[rowskey])
   if len(models)!=len(raw[rowskey]):raise ValueError('ks_native_extractor_dropped_record')
   for model,row in zip(models,raw[rowskey]):
    cid=model.comment_id
    if cid in expected:raise ValueError('ks_comment_duplicate')
    if kind=='root':
     parents[cid]='';subcounts[cid]=row.get('hasSubComments')
     if type(subcounts[cid])is not bool:raise ValueError('ks_reply_coverage_unknown')
     count=row.get('commentCount')
     if type(count)is not int or count<0 or subcounts[cid]is not (count>0):raise ValueError('ks_reply_count_unverified')
     declared_counts[cid]=count
    else:
     if parent not in subcounts or subcounts[parent]is not True:raise ValueError('ks_reply_parent_scope')
     model.parent_comment_id=parent;parents[cid]=parent
    expected[cid]=model.model_dump()
  if chains.get(('root',None))!='no_more' or any(v!='no_more'for v in chains.values()):raise ValueError('ks_pages_incomplete')
  if any(flag and chains.get(('reply',cid))!='no_more'for cid,flag in subcounts.items()):raise ValueError('ks_replies_incomplete')
  actual_counts=collections.Counter(parent for parent in parents.values()if parent)
  if any(actual_counts[cid]!=count for cid,count in declared_counts.items()):raise ValueError('ks_reply_count_mismatch')
  if len(comments)!=len(expected) or {str(x.get('comment_id'))for x in comments}!=set(expected):raise ValueError('ks_saved_comment_set')
  for row in comments:
   if not saved_matches(row,expected[str(row['comment_id'])]):raise ValueError('ks_saved_comment_changed')
  origin={'run_id':run_id,'executor':'mediacrawler_pro','capture_sha256':digest({'detail':self.detail,'pages':self.pages}),'actual_platform_source':False}
  records=[mc_runner.normalize('ks','content',videos[0],origin)]
  refs=[{'kind':kind,'url':videos[0][field],'source_field':field,'content_id':self.video_id,'bytes_verified':False}for kind,field in [('cover','video_cover_url'),('video','video_play_url')]if videos[0].get(field)]
  caption=self.detail['visionVideoDetail'].get('photo',{}).get('caption')
  if not isinstance(caption,str):raise ValueError('ks_raw_caption_missing')
  if mc_runner.contains_secret(caption):raise ValueError('ks_raw_caption_sensitive')
  encoded=caption.encode('utf-8')
  records[0]['native_projection']={'title':videos[0]['title'],'body':videos[0]['desc'],'field_limit_chars':500,'source':'original_KuaishouExtractor_and_SQLite'}
  records[0]['raw_caption']={'text':caption,'source_field':'visionVideoDetail.photo.caption','utf8_bytes':len(encoded),'utf8_sha256':hashlib.sha256(encoded).hexdigest(),'semantics':'original_caption_not_an_independent_title'}
  records[0]['title']=mc_runner.safe_text(caption,2000);records[0]['body']=mc_runner.safe_text(caption)
  records[0]['title_truncated']=len(caption)>2000;records[0]['text_truncated']=len(caption)>24000
  records[0]['title_source']='original_raw_caption';records[0]['raw_caption_preserved']=True
  records[0]['media_references']=refs;records[0]['upstream_truncation_risk']={'fields':['native_projection.title','native_projection.body'],'limit_chars':500,'reason':'original_KuaishouExtractor_slices_caption; raw_caption preserved separately'}
  records[0].pop('record_hash',None);records[0]['record_hash']=digest(records[0])
  for row in comments:
   item=copy.deepcopy(row);cid=str(item['comment_id']);item['parent_relation_basis']='reported_root_endpoint'if parents[cid]==''else'reported_subcomment_root_scope';item['parent_comment_id']='0'if parents[cid]==''else parents[cid]
   records.append(mc_runner.normalize('ks','comment',item,origin))
  return {'run_id':run_id,'records':records,'media':[],'source':{'executor':'mediacrawler_pro','coverage':'exhausted_saved_fixture_pages','cloud_ack':False,'actual_platform_source':False,'media_bytes_downloaded':False,'media_references':refs,'capture_sha256':origin['capture_sha256'],'pages':copy.deepcopy(self.pages)}}
