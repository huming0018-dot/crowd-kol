"""Read the explicitly identified first floor from the existing native response."""
from contextvars import ContextVar
from html.parser import HTMLParser
from pathlib import Path
import re

TARGET = ContextVar('crowd_tieba_body_target', default=None)
LIMIT = 1_000_000
MEDIA_KEYS = ('src', 'origin_src', 'big_cdn_src', 'big_src', 'cdn_src', 'video_url')

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.media=0; self.skip=[]
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip.append(tag)
        if not self.skip and tag in ('img','video','audio'): self.media+=1
        if not self.skip and tag in ('br','p','div'): self.parts.append(' ')
    def handle_endtag(self, tag):
        if self.skip and tag==self.skip[-1]: self.skip.pop()
        if not self.skip and tag in ('p','div'): self.parts.append(' ')
    def handle_data(self, value):
        if not self.skip: self.parts.append(value)

def content(value):
    if isinstance(value,str):
        if len(value)>LIMIT: raise ValueError('tieba_body_input_limit')
        parser=Text();parser.feed(value);parser.close()
        return re.sub(r'\s+',' ',''.join(parser.parts)).strip(),parser.media
    if not isinstance(value,list) or len(value)>2000: raise ValueError('tieba_body_content_unavailable')
    parts=[];media=0;size=0
    for row in value:
        if not isinstance(row,dict): raise ValueError('tieba_body_content_unavailable')
        is_media=any(isinstance(row.get(k),str) and row[k] for k in MEDIA_KEYS) or type(row.get('type')) is int and row['type'] in (2,3,5) or type(row.get('type')) is str and row['type'] in ('2','3','5')
        if is_media: media+=1;continue
        if 'type' in row and not (type(row['type']) is int and row['type']==0 or type(row['type']) is str and row['type']=='0'):raise ValueError('tieba_body_content_unavailable')
        value=row.get('text')
        if value is None or value=='':value=row.get('c','')
        if not isinstance(value,str): raise ValueError('tieba_body_content_unavailable')
        size+=len(value)
        if size>LIMIT: raise ValueError('tieba_body_input_limit')
        parts.append(value)
    return re.sub(r'\s+',' ',''.join(parts)).strip(),media

def first_floor(data,note_id):
    if not isinstance(data,dict) or not isinstance(note_id,str) or not re.fullmatch(r'[0-9]{1,20}',note_id):raise ValueError('tieba_body_identity_unavailable')
    thread=data.get('thread')
    def same_identity(value):
        return type(value) in (int,str) and re.fullmatch(r'[0-9]{1,20}',str(value)) is not None and str(value)==note_id
    if not isinstance(thread,dict) or not any(k in thread for k in ('id','tid')) or not all(same_identity(thread[k]) for k in ('id','tid') if k in thread):raise ValueError('tieba_body_identity_mismatch')
    def floor_number(row):
        values=[row[k] for k in ('floor','floor_num','post_no') if k in row]
        if not values:return None
        return 1 if all(type(v) is int and v==1 or type(v) is str and v=='1' for v in values) else 0
    floor=data.get('first_floor');source='first_floor'
    if isinstance(floor,dict) and floor:
        if floor_number(floor)==0:raise ValueError('tieba_body_first_floor_conflict')
    else:
        posts=data.get('post_list',[])
        if not isinstance(posts,list) or len(posts)>500:raise ValueError('tieba_body_content_unavailable')
        candidates=[r for r in posts if isinstance(r,dict) and floor_number(r)==1]
        if len(candidates)>1:raise ValueError('tieba_body_first_floor_ambiguous')
        floor=candidates[0] if candidates else None;source='post_list_explicit_floor_1'
    if floor and 'tid' in floor and not same_identity(floor['tid']):raise ValueError('tieba_body_identity_mismatch')
    origin=thread.get('origin_thread_info');origin=origin if isinstance(origin,dict) else {}
    summary=origin.get('abstract');summary_chars=len(summary) if isinstance(summary,str) else 0
    if not floor:return {'text':'','status':'summary_only' if summary_chars else 'missing_first_floor','source':'unconfirmed','media_count':0,'summary_chars':summary_chars}
    if 'content' not in floor:return {'text':'','status':'missing_body_field','source':source,'media_count':0,'summary_chars':summary_chars}
    text,media=content(floor['content'])
    return {'text':text,'status':'body_text' if text else 'media_only' if media else 'empty_first_floor','source':source,'media_count':media,'summary_chars':summary_chars}

def install_hook(client_class,extractor_class,run_dir):
    original_get=client_class.get_note_by_id;original_extract=extractor_class.extract_note_detail_from_api
    async def get(self,note_id,*args,**kwargs):
        token=TARGET.set(str(note_id))
        try:return await original_get(self,note_id,*args,**kwargs)
        finally:TARGET.reset(token)
    def extract(self,data):
        note=original_extract(self,data);target=TARGET.get()
        if target is None:return note
        body=first_floor(data,target)
        if str(note.note_id)!=target:raise ValueError('tieba_body_identity_mismatch')
        note.desc=body['text']
        # Only fixed summary fields leave the response; no payload, URL or author data.
        from mc_runner import read,write
        path=Path(run_dir)/'phase.json';phase=read(path) if path.exists() else {}
        write(path,{**phase,'tieba_body':{k:v for k,v in body.items() if k!='text'}|{'text_chars':len(body['text'])}})
        return note
    client_class.get_note_by_id=get;extractor_class.extract_note_detail_from_api=extract
