begin;
alter table crowd_kol.tasks add column executor_id uuid,add column execution_protocol int not null default 0,
 add column scan_from timestamptz,add column scan_until timestamptz,add column overlap_hours int not null default 0,add column scan_started_at timestamptz,
 add column released_at timestamptz,add column recovered_at timestamptz,add column checkpoint jsonb not null default '{"revision":0,"candidate_ids":[],"processed_ids":[],"scrolls":0,"coverage":"partial"}',
 add column max_discovery_scrolls int not null default 3 check(max_discovery_scrolls between 1 and 30),
 add column max_comment_pages int not null default 1 check(max_comment_pages between 1 and 5);
alter table crowd_kol.targets add column last_attempted_scan timestamptz,add column last_complete_coverage timestamptz,add column scan_block_reason text,add column max_discovery_scrolls int not null default 3 check(max_discovery_scrolls between 1 and 30),add column max_comment_pages int not null default 1 check(max_comment_pages between 1 and 5);
update crowd_kol.tasks set scan_from=created_at-make_interval(days=>window_days),scan_until=created_at;
alter table crowd_kol.comment_entities add column content_type text not null default 'text',add column is_placeholder boolean not null default false,add column media_count int,add column reported_reply_count bigint;
create table crowd_kol.source_attempts(owner uuid not null,request uuid not null,task uuid not null,executor_id uuid not null,
 payload_hash text not null,admission_id uuid not null,action text not null,content_id text,result jsonb not null,
 failure_reason text,state text not null default 'unknown' check(state in ('unknown','observed','failed','received')),settled_at timestamptz,
 primary key(owner,request),unique(owner,admission_id),foreign key(owner,task) references crowd_kol.tasks);
alter table crowd_kol.source_attempts enable row level security;
revoke all on crowd_kol.source_attempts from public,anon,authenticated;
create or replace function crowd_kol.enqueue(u uuid,target uuid,mode text,max_items int,comments int,days int) returns crowd_kol.tasks language plpgsql set search_path='' as $$
declare t crowd_kol.targets;r crowd_kol.tasks;b bigint;epoch bigint;binding jsonb;scan_start timestamptz;scan_end timestamptz;previous_start timestamptz;begin
 select * into t from crowd_kol.targets where owner=u and id=target and status='active' for update;
 if t.id is null then raise exception 'target_not_active';end if;
 select * into r from crowd_kol.tasks where owner=u and target_ref=target and state in ('queued','running') order by created_at limit 1;
 if r.id is not null then return r;end if;
 scan_end:=clock_timestamp();scan_start:=scan_end-make_interval(days=>days);
 if mode='periodic' then
  if days*1440<2880+t.interval_minutes then update crowd_kol.targets set scan_block_reason='invalid_overlap_window' where owner=u and id=target;return null;end if;
  select case when q.state in ('auth_required','risk_paused','error') or (q.state='partial' and q.reason is distinct from 'observed_only') then q.scan_from end into previous_start from (select * from crowd_kol.tasks z where z.owner=u and z.target_ref=target and z.scan_started_at is not null order by z.scan_started_at desc,z.created_at desc limit 1) q;
  previous_start:=least(previous_start,t.last_attempted_scan-interval '48 hours');
  if previous_start is not null and previous_start<scan_start then update crowd_kol.targets set scan_block_reason='incomplete_window_outside_authorization' where owner=u and id=target;return null;end if;
 end if;
 select credential_epoch,principal_bindings->t.platform into epoch,binding from crowd_kol.settings where owner=u;
 insert into crowd_v4.tasks(source_key,query,anchor_terms,target,status) values('kol:'||gen_random_uuid(),'KOL '||t.platform,'["KOL"]',max_items,'closed') returning id into b;
 insert into crowd_kol.tasks(owner,target_ref,bridge_task,mode,max_items,comment_limit,window_days,comment_depth,credential_epoch,principal_ref,principal_verification,principal_verification_at,max_discovery_scrolls,max_comment_pages,scan_from,scan_until,overlap_hours)
 values(u,target,b,mode,max_items,comments,days,t.comment_depth,epoch,binding->>'principal_ref',coalesce(binding->>'verification','unverified'),(binding->>'verification_at')::timestamptz,t.max_discovery_scrolls,t.max_comment_pages,scan_start,scan_end,case when mode='periodic' then 48 else 0 end) returning * into r;
 update crowd_kol.targets set scan_block_reason=null,next_due_at=case when interval_minutes>0 then clock_timestamp()+make_interval(mins=>interval_minutes) else null end where owner=u and id=target;
 return r;end $$;

create function crowd_kol.rpc_base(p_action text,p_payload jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();p crowd_v4.participants; target crowd_kol.targets; task crowd_kol.tasks; admission crowd_kol.admissions; old crowd_kol.receipts;
 binding jsonb;bindings jsonb;principal text;principal_platform text;identity_changed boolean;normalized jsonb;result jsonb;g jsonb;s jsonb;e jsonb;x jsonb;item jsonb;metrics jsonb;content crowd_kol.contents;
 req uuid;token uuid;digest text;bodyhash text;cid text;authorid text;note_budget text;act text;v_mode text;
 maxn int;comments int;days int;interval_n int;epoch bigint;version_n int;capture_time timestamptz;seen text[]:=array[]::text[];roots text[]:=array[]::text[];comment_ids text[]:=array[]::text[];entry record;evidence_id uuid;comment_entity crowd_kol.comment_entities;parent_item jsonb;comment_id_value text;parent_id_value text;root_id_value text;relation text;comment_hash text;comment_version int;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' or p.consent is distinct from 'crowd-public-v4' then raise exception 'approval_required' using errcode='42501';end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or octet_length(p_payload::text)>200000 then return jsonb_build_object('error','invalid_payload');end if;
 insert into crowd_kol.settings(owner) values(u) on conflict do nothing;
 select credential_epoch,principal_bindings into epoch,bindings from crowd_kol.settings where owner=u;
 if p_action='upsert' then
  if (p_payload-array['url','label','group','interval_minutes','target_id'])<>'{}'::jsonb then return jsonb_build_object('error','invalid_payload');end if;
  normalized:=crowd_kol.normalize_url(p_payload->>'url');interval_n:=coalesce((p_payload->>'interval_minutes')::int,0);
  if length(coalesce(p_payload->>'group',''))>120 or length(coalesce(p_payload->>'label',''))>120 or not(interval_n=0 or interval_n between 60 and 10080) then return jsonb_build_object('error','invalid_target');end if;
  if p_payload ? 'target_id' then
   select * into target from crowd_kol.targets where owner=u and id=(p_payload->>'target_id')::uuid for update;
   if target.id is null then return jsonb_build_object('error','target_missing');end if;
   if target.platform<>normalized->>'platform' or target.target_kind<>normalized->>'target_kind' or target.target_id<>normalized->>'target_id' then return jsonb_build_object('error','target_identity_immutable');end if;
  end if;
  insert into crowd_kol.targets(owner,platform,target_kind,target_id,url,label,"group",interval_minutes,next_due_at)
  values(u,normalized->>'platform',normalized->>'target_kind',normalized->>'target_id',normalized->>'url',coalesce(p_payload->>'label',''),coalesce(p_payload->>'group',''),interval_n,case when interval_n>0 then clock_timestamp() else null end)
  on conflict(owner,platform,target_kind,target_id) do update set label=excluded.label,"group"=excluded."group",interval_minutes=case when crowd_kol.targets.status='deleted' then 0 else excluded.interval_minutes end,status=case when crowd_kol.targets.status='deleted' then 'active' else crowd_kol.targets.status end,
   next_due_at=case when crowd_kol.targets.status='deleted' or excluded.interval_minutes=0 then null else coalesce(crowd_kol.targets.next_due_at,clock_timestamp()) end,updated_at=clock_timestamp()
  returning * into target;
  return jsonb_build_object('target',to_jsonb(target)-'owner');
 elsif p_action in ('stop','resume','delete_target') then
  update crowd_kol.targets set status=case p_action when 'resume' then 'active' when 'stop' then 'paused' else 'deleted' end,updated_at=clock_timestamp()
   where owner=u and id=(p_payload->>'target_id')::uuid returning * into target;
  if target.id is null then return jsonb_build_object('error','target_missing');end if;
  if p_action<>'resume' then update crowd_kol.tasks set state='cancelled',reason=p_action,finished_at=clock_timestamp() where owner=u and target_ref=target.id and state in ('queued','running');end if;
  return jsonb_build_object('target',to_jsonb(target)-'owner');
 elsif p_action='session_changed' then
  if p_payload='{}'::jsonb then
   bindings:='{}'::jsonb;identity_changed:=true;
  else
   principal_platform:=p_payload->>'platform';principal:=p_payload->>'principal_ref';
   if (p_payload-array['platform','principal_ref','verification'])<>'{}'::jsonb or principal_platform is null or principal_platform not in ('xiaohongshu','bilibili')
    or jsonb_typeof(p_payload->'principal_ref') is distinct from 'string' or principal !~ '^[a-f0-9]{64}$'
    or p_payload->>'verification' is distinct from 'rendered_account_navigation' then return jsonb_build_object('error','invalid_principal');end if;
   identity_changed:=(bindings->principal_platform->>'principal_ref') is distinct from principal;
   binding:=jsonb_build_object('principal_ref',principal,'verification','rendered_account_navigation','verification_at',clock_timestamp());
   bindings:=jsonb_set(bindings,array[principal_platform],binding,true);
  end if;
  update crowd_kol.settings set principal_bindings=bindings,credential_epoch=credential_epoch+case when identity_changed then 1 else 0 end where owner=u returning credential_epoch into epoch;
  if identity_changed then update crowd_kol.tasks set state='cancelled',reason='session_changed',finished_at=clock_timestamp() where owner=u and state in ('queued','running');end if;
  return jsonb_build_object('credential_epoch',epoch,'principal_bindings',bindings,'identity_changed',identity_changed);
 elsif p_action='start' then
  v_mode:=coalesce(p_payload->>'mode','manual');maxn:=coalesce((p_payload->>'max_items')::int,2);comments:=coalesce((p_payload->>'comment_limit')::int,0);days:=coalesce((p_payload->>'window_days')::int,30);
  if v_mode not in ('manual','history','periodic') or maxn not between 1 and 10 or comments not between 0 and 20 or days not between 1 and 3650
    or coalesce((p_payload->>'comment_depth')::int,1) not in (1,2) then return jsonb_build_object('error','invalid_task_limits');end if;
  if v_mode='periodic' then
   interval_n:=coalesce((p_payload->>'interval_minutes')::int,60);
   if interval_n not between 60 and 10080 then return jsonb_build_object('error','invalid_interval');end if;
   update crowd_kol.targets set interval_minutes=interval_n where owner=u and id=(p_payload->>'target_id')::uuid;
  end if;
  update crowd_kol.targets set max_items=maxn,comment_limit=comments,window_days=days,comment_depth=coalesce((p_payload->>'comment_depth')::int,1) where owner=u and id=(p_payload->>'target_id')::uuid;
  task:=crowd_kol.enqueue(u,(p_payload->>'target_id')::uuid,v_mode,maxn,comments,days);
  return jsonb_build_object('task',to_jsonb(task)-'owner'-'bridge_task');
 elsif p_action='claim' then
  -- No parallel legacy lease; KOL does not hijack or renew another collector's task.
  if exists(select from crowd_v4.tasks where claimed_by=u and status='leased' and lease_until>clock_timestamp()) then return jsonb_build_object('task',null,'reason','legacy_task_active');end if;
  update crowd_kol.tasks set state='partial',reason='lease_expired',finished_at=clock_timestamp() where owner=u and state='running' and lease_until<=clock_timestamp();
  for target in select * from crowd_kol.targets where owner=u and status='active' and interval_minutes>0 and next_due_at<=clock_timestamp() order by next_due_at limit 10 loop
   perform crowd_kol.enqueue(u,target.id,'periodic',target.max_items,target.comment_limit,target.window_days);
  end loop;
  select * into task from crowd_kol.tasks where owner=u and credential_epoch=epoch and state='running' order by created_at limit 1 for update;
  if task.id is null then select * into task from crowd_kol.tasks where owner=u and credential_epoch=epoch and state='queued' order by created_at limit 1 for update;end if;
  if task.id is null then return jsonb_build_object('task',null);end if;
  select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
  if target.status<>'active' then return jsonb_build_object('task',null);end if;
  update crowd_kol.tasks set state='running',lease_token=coalesce(lease_token,gen_random_uuid()),lease_until=clock_timestamp()+interval '20 minutes' where owner=u and id=task.id returning * into task;
  return jsonb_build_object('task',(to_jsonb(task)-'owner'-'bridge_task')||jsonb_build_object('platform',target.platform,'target_kind',target.target_kind,'target_id',target.target_id,'url',target.url,'include_replies',task.comment_depth=2,
   'refresh_ids',(select coalesce(jsonb_agg(q.content_id),'[]'::jsonb) from (select content_id from crowd_kol.contents where owner=u and platform=target.platform and last_seen_at<clock_timestamp()-interval '24 hours' and (target.target_kind='content' and content_id=target.target_id or target.target_kind='creator' and creator_id=target.target_id) order by last_seen_at limit 1)q),
   'known_ids',(select coalesce(jsonb_agg(q.content_id),'[]'::jsonb) from (select content_id from crowd_kol.contents where owner=u and platform=target.platform and (target.target_kind='content' and content_id=target.target_id or target.target_kind='creator' and creator_id=target.target_id) order by last_seen_at desc limit 500)q)));
 elsif p_action='guard' then
  act:=p_payload->>'action';cid:=p_payload->>'content_id';
  if act not in ('search','detail','scroll','comment') or act is null then return jsonb_build_object('error','invalid_action');end if;
  select * into task from crowd_kol.tasks where owner=u and id=(p_payload->>'task')::uuid for update;
  if task.id is null or task.lease_token is distinct from (p_payload->>'lease')::uuid or task.state<>'running' or task.lease_until<=clock_timestamp() or task.credential_epoch<>epoch then return jsonb_build_object('allowed',false,'reason','lease_expired','wait_ms',0);end if;
  select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
  if target.status<>'active' then return jsonb_build_object('allowed',false,'reason','target_paused','wait_ms',0);end if;
  if task.principal_ref is not null and task.principal_ref is distinct from (bindings->target.platform->>'principal_ref') then return jsonb_build_object('allowed',false,'reason','platform_identity_changed','wait_ms',0);end if;
  maxn:=case act when 'detail' then task.max_items when 'search' then case when task.execution_protocol=1 then 3 else 1 end when 'scroll' then task.max_discovery_scrolls else case when task.comment_limit>0 then task.max_items*task.max_comment_pages else 0 end end;
  if (task.attempts->>act)::int>=maxn then return jsonb_build_object('allowed',false,'reason','task_budget','wait_ms',0);end if;
  if act in ('detail','comment') then
   if cid is null or (target.platform='xiaohongshu' and cid !~ '^[a-f0-9]{24}$') or (target.platform='bilibili' and cid !~ '^BV[0-9A-Za-z]{10}$') then return jsonb_build_object('error','invalid_content_id');end if;
   if target.target_kind='content' and target.target_id<>cid then return jsonb_build_object('error','target_mismatch');end if;
  end if;
  -- Existing audited guard remains the stricter shared source-action budget.
  note_budget:=substr(md5('kol:'||target.platform||':'||coalesce(cid,'')),1,24);
  update crowd_v4.tasks set status='leased',claimed_by=u,lease_token=task.lease_token,lease_until=task.lease_until where id=task.bridge_task;
  g:=public.crowd_v4_guard(act,task.bridge_task,note_budget);
  update crowd_v4.tasks set status='closed' where id=task.bridge_task;
  if coalesce((g->>'allowed')::boolean,false)=false then return g;end if;
  if task.scan_started_at is null then update crowd_kol.targets set last_attempted_scan=clock_timestamp() where owner=u and id=target.id;update crowd_kol.tasks set scan_started_at=clock_timestamp() where owner=u and id=task.id;end if;
  update crowd_kol.tasks set attempts=jsonb_set(attempts,array[act],to_jsonb((attempts->>act)::int+1)) where owner=u and id=task.id;
  insert into crowd_kol.admissions(owner,task,lease,action,content_id) values(u,task.id,task.lease_token,act,cid) returning * into admission;
  return g||jsonb_build_object('admission_id',admission.id);
 elsif p_action='profile' then
  req:=(p_payload->>'request')::uuid;token:=(p_payload->>'lease')::uuid;
  if req is null or token is null then return jsonb_build_object('error','invalid_envelope');end if;
  digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
  select * into old from crowd_kol.receipts where owner=u and request=req;
  if old.request is not null then if old.payload_hash<>digest then return jsonb_build_object('error','request_reused');end if;return old.result;end if;
  select * into task from crowd_kol.tasks t where t.owner=u and t.id=(p_payload->>'task')::uuid;
  if task.id is null or task.lease_token is distinct from token then return jsonb_build_object('error','task_missing');end if;
  select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
  select * into admission from crowd_kol.admissions a where a.owner=u and a.id=(p_payload->>'admission_id')::uuid and a.task=task.id and a.lease=token and a.action='search' for update;
  if admission.id is null then return jsonb_build_object('error','admission_missing');end if;
  if admission.used_request is not null then return jsonb_build_object('error','admission_used');end if;
  if admission.accept_until<=clock_timestamp() then return jsonb_build_object('error','admission_expired');end if;
  result:=p_payload->'profile';
  if target.target_kind<>'creator' or jsonb_typeof(result) is distinct from 'object' or not(result ?& array['author_id','url','nickname','public_handle','metrics','captured_at','source','parser_version'])
   or (result-array['author_id','url','nickname','public_handle','metrics','captured_at','source','parser_version'])<>'{}'::jsonb
   or result->>'author_id' is distinct from target.target_id or result->>'url' is distinct from target.url
   or result->>'source' is distinct from 'rendered_public_dom' or coalesce(result->>'parser_version','') !~ '^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}$'
   or jsonb_typeof(result->'nickname') not in ('string','null') or length(result->>'nickname')>100
   or jsonb_typeof(result->'public_handle') not in ('string','null') or length(result->>'public_handle')>100
   or jsonb_typeof(result->'metrics') is distinct from 'object'
   then return jsonb_build_object('error','invalid_profile');end if;
  for entry in select key,value from jsonb_each(result->'metrics') loop
   item:=entry.value;
   if entry.key not in ('followers','notes','likes_collected') or jsonb_typeof(item)<>'object'
    or (item-array['value','label','status'])<>'{}'::jsonb or not(item ?& array['value','label','status'])
    or jsonb_typeof(item->'value') not in ('number','null') or (item->'value'<>'null'::jsonb and coalesce(item->>'value','') !~ '^[0-9]{1,10}$')
    or jsonb_typeof(item->'label') not in ('string','null') or length(item->>'label')>200
    or coalesce(item->>'status','') not in ('exact','approximate','not_visible','not_requested','unparsed')
    or ((item->>'status' in ('exact','approximate')) is distinct from (item->'value'<>'null'::jsonb)) then return jsonb_build_object('error','invalid_profile');end if;
   if item->'value'<>'null'::jsonb and (item->>'value')::numeric>2147483647 then return jsonb_build_object('error','invalid_profile');end if;
  end loop;
  capture_time:=(result->>'captured_at')::timestamptz;
  if capture_time is null or capture_time>clock_timestamp()+interval '5 minutes' or capture_time<admission.issued_at-interval '5 minutes' then return jsonb_build_object('error','invalid_timestamp');end if;
  insert into crowd_kol.profiles(owner,request,target_ref,platform,author_id,profile) values(u,req,target.id,target.platform,target.target_id,result);
  update crowd_kol.admissions set used_request=req where owner=u and crowd_kol.admissions.id=admission.id;
  result:=jsonb_build_object('gate','received','request',req,'task',task.id,'kind','profile','received_at',clock_timestamp(),'source_kind','rendered_public_dom','reward_eligible',false);
  insert into crowd_kol.receipts(owner,request,payload_hash,result) values(u,req,digest,result);return result;
 elsif p_action='submit' then
  req:=(p_payload->>'request')::uuid;token:=(p_payload->>'lease')::uuid;
  if req is null or p_payload->>'task' is null or token is null then return jsonb_build_object('error','invalid_envelope');end if;
  digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
  select * into old from crowd_kol.receipts where owner=u and request=req;
  if old.request is not null then
   if old.payload_hash<>digest then return jsonb_build_object('error','request_reused');end if;
   return old.result;
  end if;
  -- Qualify the PL/pgSQL variable to avoid an unscoped owner/task lookup.
  select * into task from crowd_kol.tasks t where t.owner=u and t.id=(p_payload->>'task')::uuid for update;
  if task.id is null or task.lease_token is distinct from token then return jsonb_build_object('error','task_missing');end if;
  select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
  select * into admission from crowd_kol.admissions a where a.owner=u and a.id=(p_payload->>'admission_id')::uuid and a.task=task.id and a.lease=token and a.action='detail' for update;
  if admission.id is null then return jsonb_build_object('error','admission_missing');end if;
  if admission.used_request is not null then return jsonb_build_object('error','admission_used');end if;
  if admission.accept_until<=clock_timestamp() then return jsonb_build_object('error','admission_expired');end if;
  result:=p_payload->'record';s:=result->'standard';e:=result->'evidence';x:=result->'extra';cid:=s->>'note_id';authorid:=x#>>'{author,id}';
  if jsonb_typeof(result) is distinct from 'object' or (result-array['schema_version','standard','extra','evidence'])<>'{}'::jsonb or result->>'schema_version' is distinct from '4'
   or jsonb_typeof(s) is distinct from 'object' or jsonb_typeof(e) is distinct from 'object' or jsonb_typeof(x) is distinct from 'object'
   or (s-array['platform','note_id','url','title','captured_at','published_at','author_display','like_count','collect_count','comment_count','view_count','share_count','danmaku_count'])<>'{}'::jsonb
   or (e-array['text','original_length','truncated','parser_version','source','selector'])<>'{}'::jsonb
   or (x-array['author','author_opinion_quotes','comments','media_present','field_observations','metric_labels','published_label','hashtags','content_type','comment_status','replies_status','media_refs','media_status'])<>'{}'::jsonb
   or s->>'platform' is distinct from target.platform or cid is distinct from admission.content_id or e->>'source' is distinct from 'rendered_public_dom'
   or jsonb_typeof(s->'title') is distinct from 'string' or length(s->>'title')>300
   or jsonb_typeof(e->'text') is distinct from 'string' or length(e->>'text')>24000
   or (length(s->>'title')=0 and length(e->>'text')=0 and x->>'media_present' is distinct from 'true')
   or coalesce(e->>'original_length','') !~ '^[0-9]{1,8}$' or jsonb_typeof(e->'truncated') is distinct from 'boolean'
   or coalesce(e->>'parser_version','') !~ '^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}$'
   or jsonb_typeof(x->'author_opinion_quotes') is distinct from 'array'
   or not(s ?& array['platform','note_id','url','title','captured_at','published_at','author_display','like_count','collect_count','comment_count'])
   then return jsonb_build_object('error','invalid_record');end if;
  if (e->>'original_length')::int<length(e->>'text') or jsonb_array_length(x->'author_opinion_quotes')>30
   or exists(select from jsonb_array_elements(x->'author_opinion_quotes')q where jsonb_typeof(q)<>'string' or strpos(e->>'text',q#>>'{}')=0)
   or jsonb_typeof(s->'author_display') not in ('null','string') or length(s->>'author_display')>100
   or jsonb_typeof(s->'published_at') not in ('null','string')
   or (x ? 'media_present' and jsonb_typeof(x->'media_present')<>'boolean')
   then return jsonb_build_object('error','invalid_record');end if;
  if (e ? 'selector' and (jsonb_typeof(e->'selector') not in ('string','null') or length(e->>'selector')>500))
   or (x ? 'published_label' and (jsonb_typeof(x->'published_label') not in ('string','null') or length(x->>'published_label')>400))
   or (x ? 'content_type' and x->>'content_type' not in ('note','video','article'))
   or (x ? 'comment_status' and x->>'comment_status' not in ('not_requested','not_visible','visible_sample'))
   or (x ? 'replies_status' and x->>'replies_status' not in ('not_requested','not_visible','visible_loaded_only')) then return jsonb_build_object('error','invalid_record');end if;
  if x ? 'hashtags' then
   if jsonb_typeof(x->'hashtags')<>'array' or jsonb_array_length(x->'hashtags')>50 then return jsonb_build_object('error','invalid_record');end if;
   if exists(select from jsonb_array_elements(x->'hashtags')q where jsonb_typeof(q)<>'string' or length(q#>>'{}')>100) then return jsonb_build_object('error','invalid_record');end if;
  end if;
  if x ? 'metric_labels' then
   if jsonb_typeof(x->'metric_labels')<>'object' then return jsonb_build_object('error','invalid_metrics');end if;
   if exists(select from jsonb_each(x->'metric_labels') a(k,v) where k not in ('like_count','collect_count','comment_count','view_count','share_count','danmaku_count') or jsonb_typeof(v) not in ('string','null') or length(v#>>'{}')>200) then return jsonb_build_object('error','invalid_metrics');end if;
  end if;
  if x ? 'field_observations' then
   if jsonb_typeof(x->'field_observations')<>'object' then return jsonb_build_object('error','invalid_metrics');end if;
   for entry in select key,value from jsonb_each(x->'field_observations') loop
    item:=entry.value;
    if entry.key not in ('like_count','collect_count','comment_count','view_count','share_count','danmaku_count') or jsonb_typeof(item)<>'object'
     or (item-array['value','label','status'])<>'{}'::jsonb or item->'value' is distinct from s->entry.key
     or coalesce(item->>'status','') not in ('exact','approximate','not_visible','not_requested','unparsed')
     or jsonb_typeof(item->'label') not in ('string','null') or length(item->>'label')>200
     or ((item->>'status' in ('exact','approximate')) is distinct from (item->'value'<>'null'::jsonb)) then return jsonb_build_object('error','invalid_metrics');end if;
   end loop;
  end if;
  normalized:=crowd_kol.normalize_url(s->>'url');
  if normalized->>'platform'<>target.platform or normalized->>'target_kind'<>'content' or normalized->>'target_id'<>cid or normalized->>'url'<>s->>'url'
   or (target.target_kind='content' and target.target_id<>cid) then return jsonb_build_object('error','target_mismatch');end if;
  if x ? 'author' and x->'author'<>'null'::jsonb then
   if jsonb_typeof(x->'author')<>'object' or ((x->'author')-array['id','url'])<>'{}'::jsonb then return jsonb_build_object('error','invalid_author');end if;
   normalized:=crowd_kol.normalize_url(x#>>'{author,url}');
   if normalized->>'platform'<>target.platform or normalized->>'target_kind'<>'creator' or normalized->>'target_id' is distinct from authorid or normalized->>'url' is distinct from x#>>'{author,url}' then return jsonb_build_object('error','invalid_author');end if;
  end if;
  if target.target_kind='creator' and target.target_id is distinct from authorid then return jsonb_build_object('error','author_mismatch');end if;
  if exists(select from jsonb_each(s)a(k,v) where k in ('like_count','collect_count','comment_count','view_count','share_count','danmaku_count') and
    (jsonb_typeof(v) not in ('null','number') or v<>'null'::jsonb and v::text !~ '^[0-9]{1,10}$')) then return jsonb_build_object('error','invalid_metrics');end if;
  if exists(select from jsonb_each(s)a(k,v) where k in ('like_count','collect_count','comment_count','view_count','share_count','danmaku_count') and v<>'null'::jsonb and v::text::numeric>2147483647) then return jsonb_build_object('error','invalid_metrics');end if;
  capture_time:=(s->>'captured_at')::timestamptz;
  if capture_time is null or capture_time>clock_timestamp()+interval '5 minutes' or capture_time<admission.issued_at-interval '5 minutes' then return jsonb_build_object('error','invalid_timestamp');end if;
  if s->>'published_at' is not null then
   if s->>'published_at' !~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$' then return jsonb_build_object('error','invalid_published_date');end if;
   perform (s->>'published_at')::date;
   if (task.execution_protocol=0 and (s->>'published_at')::date<(task.created_at at time zone 'Asia/Shanghai')::date-task.window_days)
    or (task.execution_protocol=1 and (((s->>'published_at')::date+1)::timestamp at time zone 'UTC')<=coalesce(task.scan_from,task.created_at-make_interval(days=>task.window_days))) then return jsonb_build_object('error','outside_window');end if;
  end if;
  -- Allow ordinary public links in prose, never serialized credential assignments.
  if result::text ~* '(https?://[^[:space:]]*[?&#](xsec_token|access_token|refresh_token|authorization|cookie|password|token)=|https?://[^/@[:space:]]+@)'
   then return jsonb_build_object('error','credential_material');end if;
  if x ? 'media_status' and (jsonb_typeof(x->'media_status') is distinct from 'string' or x->>'media_status' not in ('public_refs_available','no_eligible_public_ref')) then return jsonb_build_object('error','invalid_media');end if;
  if x ? 'media_refs' then
   if jsonb_typeof(x->'media_refs') is distinct from 'array' or jsonb_array_length(x->'media_refs')>20 then return jsonb_build_object('error','invalid_media');end if;
   for item in select value from jsonb_array_elements(x->'media_refs') loop
    if jsonb_typeof(item) is distinct from 'object' or (item-array['url','kind','source','status'])<>'{}'::jsonb
     or jsonb_typeof(item->'url') is distinct from 'string' or length(item->>'url')>2048
     or item->>'url' !~ '^https://([a-z0-9-]+\.)*(xhscdn\.com|xhsimg\.com|hdslb\.com)/[^?#[:space:]\\]*$'
     or item->>'kind' is null or item->>'kind' not in ('image','audio','video') or item->>'source' is distinct from 'rendered_public_dom'
     or item->>'status' is distinct from 'discovered_not_downloaded' then return jsonb_build_object('error','invalid_media');end if;
   end loop;
  end if;
  if x ? 'comments' then
   item:=x->'comments';
   if jsonb_typeof(item)<>'object' or (item-array['items','coverage','complete','truncated','captured_count','panel_found','loaded_count','omitted_count','more_available'])<>'{}'::jsonb or jsonb_typeof(item->'items') is distinct from 'array' or item->>'coverage' is distinct from 'visible_loaded_only' or item->>'complete' is distinct from 'false'
    or jsonb_typeof(item->'truncated') is distinct from 'boolean' or jsonb_array_length(item->'items')>task.comment_limit
    or item->>'captured_count' is distinct from jsonb_array_length(item->'items')::text then return jsonb_build_object('error','invalid_comments');end if;
   for item in select value from jsonb_array_elements(x#>'{comments,items}') loop
    if (item-array['key','comment_id','parent_key','is_reply','author_display','text','original_length','truncated','like_count','like_label','published_label','content_type','is_placeholder','media_count','reported_reply_count'])<>'{}'::jsonb
     or coalesce(item->>'key','') !~ '^comment-[1-9][0-9]{0,2}$' or item->>'key'=any(seen)
     or (item->>'parent_key' is not null and (task.comment_depth<>2 or not(item->>'parent_key'=any(roots))))
     or jsonb_typeof(item->'text') is distinct from 'string' or length(item->>'text')>2000
     or coalesce(item->>'original_length','') !~ '^[0-9]{1,8}$' or jsonb_typeof(item->'truncated') is distinct from 'boolean'
     then return jsonb_build_object('error','invalid_comments');end if;
    if (item ? 'content_type' and (jsonb_typeof(item->'content_type') is distinct from 'string' or item->>'content_type' not in ('text','image','mixed')))
     or (item ? 'is_placeholder' and jsonb_typeof(item->'is_placeholder') is distinct from 'boolean')
     or (item ? 'media_count' and item->'media_count'<>'null'::jsonb and (jsonb_typeof(item->'media_count')<>'number' or item->>'media_count' !~ '^[0-9]{1,3}$'))
     or (item ? 'reported_reply_count' and item->'reported_reply_count'<>'null'::jsonb and (jsonb_typeof(item->'reported_reply_count')<>'number' or item->>'reported_reply_count' !~ '^[0-9]{1,10}$')) then return jsonb_build_object('error','invalid_comments');end if;
    if (item->>'media_count')::int>100 or (item->>'reported_reply_count')::numeric>2147483647 then return jsonb_build_object('error','invalid_comments');end if;
    if item->>'content_type'='image' then
     if item->>'text' is distinct from '' or item->'is_placeholder' is distinct from 'true'::jsonb or (item->>'original_length')::int<>0 or item->'truncated' is distinct from 'false'::jsonb or coalesce((item->>'media_count')::int,0)<1 then return jsonb_build_object('error','invalid_comments');end if;
    else
     if length(item->>'text')=0 or coalesce((item->>'is_placeholder')::boolean,false) or (item->>'original_length')::int<length(item->>'text')
      or (item->>'content_type'='mixed' and coalesce((item->>'media_count')::int,0)<1)
      or (coalesce(item->>'content_type','text')='text' and coalesce((item->>'media_count')::int,0)>0) then return jsonb_build_object('error','invalid_comments');end if;
    end if;
    if (item ? 'author_display' and item->'author_display'<>'null'::jsonb)
     or (item ? 'comment_id' and item->'comment_id'<>'null'::jsonb and coalesce(item->>'comment_id','') !~ '^[a-zA-Z0-9_-]{1,80}$')
     or (item ? 'is_reply' and jsonb_typeof(item->'is_reply')<>'boolean')
     or (item ? 'like_count' and item->'like_count'<>'null'::jsonb and (jsonb_typeof(item->'like_count')<>'number' or (item->>'like_count') !~ '^[0-9]{1,10}$'))
     or (item ? 'like_label' and (jsonb_typeof(item->'like_label') not in ('string','null') or length(item->>'like_label')>100))
     or (item ? 'published_label' and (jsonb_typeof(item->'published_label') not in ('string','null') or length(item->>'published_label')>100))
     then return jsonb_build_object('error','invalid_comments');end if;
    if item->>'like_count' is not null and (item->>'like_count')::numeric>2147483647 then return jsonb_build_object('error','invalid_comments');end if;
    if item->>'parent_key' is not null and item->>'is_reply'='false' then return jsonb_build_object('error','invalid_comments');end if;
    if item->>'comment_id' is not null then
     if item->>'comment_id'=any(comment_ids) then return jsonb_build_object('error','duplicate_comment_id');end if;
     comment_ids:=array_append(comment_ids,item->>'comment_id');
    end if;
    if item->>'parent_key' is null then roots:=array_append(roots,item->>'key');end if;
    seen:=array_append(seen,item->>'key');
   end loop;
  end if;
  metrics:=jsonb_build_object('like_count',s->'like_count','collect_count',s->'collect_count','comment_count',s->'comment_count','view_count',s->'view_count','share_count',s->'share_count','danmaku_count',s->'danmaku_count','observations',x->'field_observations','labels',x->'metric_labels');
  bodyhash:=encode(sha256(convert_to(jsonb_build_object('platform',target.platform,'content_id',cid,'creator_id',authorid,'title',s->'title','body',e->'text','published_at',s->'published_at','content_type',x->'content_type','hashtags',x->'hashtags')::text,'UTF8')),'hex');
  select * into content from crowd_kol.contents c where c.owner=u and c.platform=target.platform and c.content_id=cid for update;
  version_n:=case when content.content_id is null then 1 when content.content_hash=bodyhash then content.version else content.version+1 end;
  insert into crowd_kol.contents(owner,platform,content_id,creator_id,url,title,body,published_at,metrics,version,content_hash,latest_record)
   values(u,target.platform,cid,authorid,s->>'url',s->>'title',e->>'text',s->>'published_at',metrics,version_n,bodyhash,result)
   on conflict(owner,platform,content_id) do update set creator_id=excluded.creator_id,url=excluded.url,title=excluded.title,body=excluded.body,published_at=excluded.published_at,metrics=excluded.metrics,
    version=excluded.version,content_hash=excluded.content_hash,latest_record=excluded.latest_record,last_seen_at=clock_timestamp();
  insert into crowd_kol.versions(owner,platform,content_id,version,record) values(u,target.platform,cid,version_n,result) on conflict do nothing;
  insert into crowd_kol.snapshots(owner,request,task,platform,content_id,metrics,captured_at) values(u,req,task.id,target.platform,cid,metrics,capture_time);
  for item in select value from jsonb_array_elements(coalesce(x#>'{comments,items}','[]'::jsonb)) loop
   insert into crowd_kol.comments values(u,req,item->>'key',item->>'parent_key',item->>'text',(item->>'truncated')::boolean,item);
   comment_id_value:=item->>'comment_id';
   if comment_id_value is not null then
    parent_id_value:=null;root_id_value:=null;relation:='unknown';
    if item->>'parent_key' is not null then
     select value into parent_item from jsonb_array_elements(x#>'{comments,items}') a(value) where value->>'key'=item->>'parent_key';
     parent_id_value:=parent_item->>'comment_id';
     relation:=case when parent_id_value is null then 'orphan' else 'parent_observed' end;
     if parent_item->>'parent_key' is null and parent_item->>'is_reply'='false' then root_id_value:=parent_id_value;end if;
    elsif item->>'is_reply'='false' then root_id_value:=comment_id_value;relation:='root';
    elsif item->>'is_reply'='true' then relation:='orphan';end if;
    comment_hash:=encode(sha256(convert_to(jsonb_build_object('body',item->'text','truncated',item->'truncated','original_length',item->'original_length')::text,'UTF8')),'hex');
    if item->>'content_type' in ('image','mixed') then comment_hash:=encode(sha256(convert_to(jsonb_build_object('text_hash',comment_hash,'content_type',item->'content_type','is_placeholder',item->'is_placeholder','media_count',item->'media_count')::text,'UTF8')),'hex');end if;
    select * into comment_entity from crowd_kol.comment_entities c where c.owner=u and c.platform=target.platform and c.content_id=cid and c.comment_id=comment_id_value for update;
    comment_version:=case when comment_entity.comment_id is null then 1 when comment_entity.body_hash=comment_hash then comment_entity.version else comment_entity.version+1 end;
    insert into crowd_kol.comment_entities(owner,platform,content_id,comment_id,parent_comment_id,root_comment_id,relationship_status,is_reply,body,truncated,like_count,like_label,published_label,version,body_hash,latest_request,content_type,is_placeholder,media_count,reported_reply_count)
     values(u,target.platform,cid,comment_id_value,parent_id_value,root_id_value,relation,(item->>'is_reply')::boolean,item->>'text',(item->>'truncated')::boolean,(item->>'like_count')::bigint,item->>'like_label',item->>'published_label',comment_version,comment_hash,req,coalesce(item->>'content_type','text'),coalesce((item->>'is_placeholder')::boolean,false),(item->>'media_count')::int,(item->>'reported_reply_count')::bigint)
     on conflict(owner,platform,content_id,comment_id) do update set parent_comment_id=excluded.parent_comment_id,root_comment_id=excluded.root_comment_id,relationship_status=excluded.relationship_status,is_reply=excluded.is_reply,
      content_type=excluded.content_type,is_placeholder=excluded.is_placeholder,media_count=excluded.media_count,reported_reply_count=excluded.reported_reply_count,body=excluded.body,truncated=excluded.truncated,like_count=excluded.like_count,like_label=excluded.like_label,published_label=excluded.published_label,version=excluded.version,body_hash=excluded.body_hash,latest_request=excluded.latest_request,last_seen_at=clock_timestamp();
    insert into crowd_kol.comment_versions(owner,platform,content_id,comment_id,version,request,record) values(u,target.platform,cid,comment_id_value,comment_version,req,item) on conflict do nothing;
   end if;
  end loop;
  update crowd_kol.admissions set used_request=req where owner=u and crowd_kol.admissions.id=admission.id;
  update crowd_kol.tasks set received=received+1 where owner=u and crowd_kol.tasks.id=task.id;
  result:=jsonb_build_object('gate','received','request',req,'task',task.id,'content_id',cid,'received_at',clock_timestamp(),'version',version_n,'inserted',content.content_id is null,'source_kind','rendered_public_dom','reward_eligible',false);
  insert into crowd_kol.receipts(owner,request,payload_hash,result) values(u,req,digest,result);
  return result;
 elsif p_action='finish' then
  select * into task from crowd_kol.tasks t where t.owner=u and t.id=(p_payload->>'task')::uuid for update;
  if task.id is null or task.lease_token is distinct from (p_payload->>'lease')::uuid then return jsonb_build_object('error','lease_lost');end if;
  act:=p_payload->>'reason';if act not in ('completed','partial','auth_required','risk_paused','cancelled','error','observed_only') or act is null then return jsonb_build_object('error','invalid_finish');end if;
  if task.state='running' and act='risk_paused' then
   v_mode:=coalesce(p_payload->>'risk_type','rate_limit');if v_mode not in ('captcha','rate_limit') then return jsonb_build_object('error','invalid_risk_type');end if;
   perform public.crowd_v4_guard(v_mode);
  end if;
  v_mode:=act;
  if act='observed_only' then
   select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
   if target.target_kind<>'creator' or (task.checkpoint->>'revision')::int<1
    or not exists(select from crowd_kol.source_attempts a where a.owner=u and a.task=task.id and a.action='search' and a.state='observed')
    or exists(select from crowd_kol.source_attempts a where a.owner=u and a.task=task.id and a.state in ('unknown','failed'))
    or exists(select from crowd_kol.snapshots s where s.owner=u and s.task=task.id and not(task.checkpoint->'processed_ids' ? s.content_id)) then return jsonb_build_object('error','invalid_finish');end if;
   act:='partial';
  end if;
  if p_payload ? 'detail_reason' then
   if act<>'error' or p_payload->>'detail_reason' is null or p_payload->>'detail_reason' not in ('source_not_found','source_private','source_deleted','parser_paused') then return jsonb_build_object('error','invalid_finish');end if;
   v_mode:=p_payload->>'detail_reason';
  end if;
  if act='completed' then
   select * into target from crowd_kol.targets where owner=u and id=task.target_ref;
   if task.received=0 then act:='partial';v_mode:='no_received_content';
   elsif target.target_kind='creator' then act:='partial';v_mode:='observed_only';end if;
  end if;
  if task.state='running' then update crowd_kol.tasks set state=act,reason=v_mode,finished_at=clock_timestamp() where owner=u and crowd_kol.tasks.id=task.id returning * into task;end if;
  return jsonb_build_object('task',to_jsonb(task)-'owner'-'bridge_task');
 elsif p_action='attach_evidence' then
  cid:=p_payload->>'content_id';v_mode:=p_payload->>'platform';act:=p_payload->>'kind';e:=p_payload->'evidence';
  if (p_payload-array['platform','content_id','kind','authorization_ref','evidence'])<>'{}'::jsonb
   or coalesce(act,'') not in ('ocr','transcript','demographics') or length(coalesce(p_payload->>'authorization_ref','')) not between 1 and 200
   or jsonb_typeof(e) is distinct from 'object' or (e-array['source_kind','asset_sha256','observed_at','raw_text','blocks','population','dimension','sample_size','coverage_period','aggregate_values','truncated','coverage','processor'])<>'{}'::jsonb
   or (e ? 'processor' and (jsonb_typeof(e->'processor') is distinct from 'string' or e->>'processor' not in ('apple_speech_ondevice','manual_import','apple_vision','faster_whisper_local')))
   or (e ? 'truncated' and jsonb_typeof(e->'truncated')<>'boolean') or (e ? 'coverage' and e->>'coverage' is distinct from 'local_file_bounded')
   or e->>'source_kind' is distinct from 'authorized_local_file' or coalesce(e->>'asset_sha256','') !~ '^[a-f0-9]{64}$'
   then return jsonb_build_object('error','invalid_evidence');end if;
  perform 1 from crowd_kol.contents c where c.owner=u and c.platform=v_mode and c.content_id=cid for update;
  if not found then return jsonb_build_object('error','content_missing');end if;
  capture_time:=(e->>'observed_at')::timestamptz;
  if capture_time is null or not isfinite(capture_time) or capture_time>clock_timestamp()+interval '5 minutes' then return jsonb_build_object('error','invalid_timestamp');end if;
  if act='demographics' then
   if e ? 'raw_text' or e ? 'blocks' or jsonb_typeof(e->'population') is distinct from 'string' or jsonb_typeof(e->'dimension') is distinct from 'string' or jsonb_typeof(e->'coverage_period') is distinct from 'string' or length(coalesce(e->>'population','')) not between 1 and 200 or length(coalesce(e->>'dimension','')) not between 1 and 100
    or length(coalesce(e->>'coverage_period','')) not between 1 and 200 or jsonb_typeof(e->'sample_size') is distinct from 'number' or coalesce(e->>'sample_size','') !~ '^[0-9]{1,10}$'
    or jsonb_typeof(e->'aggregate_values') is distinct from 'object' then return jsonb_build_object('error','invalid_aggregate');end if;
   if (e->>'sample_size')::numeric>2147483647 or (select count(*) from jsonb_each(e->'aggregate_values')) not between 1 and 100 or exists(select from jsonb_each(e->'aggregate_values')a(k,v) where length(k) not between 1 and 100 or jsonb_typeof(v)<>'number') then return jsonb_build_object('error','invalid_aggregate');end if;
   if exists(select from jsonb_each(e->'aggregate_values')a(k,v) where (v#>>'{}')::numeric<0) then return jsonb_build_object('error','invalid_aggregate');end if;
  else
   if e ?| array['population','dimension','sample_size','coverage_period','aggregate_values'] then return jsonb_build_object('error','invalid_evidence');end if;
   if e ? 'raw_text' and (jsonb_typeof(e->'raw_text')<>'string' or length(e->>'raw_text')>24000) then return jsonb_build_object('error','invalid_evidence');end if;
   if act='transcript' and (length(coalesce(e->>'raw_text',''))=0 or e ? 'blocks') then return jsonb_build_object('error','invalid_evidence');end if;
   if act='ocr' and not(e ? 'raw_text' or e ? 'blocks') then return jsonb_build_object('error','invalid_evidence');end if;
   if e ? 'blocks' then
    if jsonb_typeof(e->'blocks')<>'array' or jsonb_array_length(e->'blocks')>200 then return jsonb_build_object('error','invalid_evidence');end if;
    for item in select value from jsonb_array_elements(e->'blocks') loop
     if jsonb_typeof(item)<>'object' or (item-array['text','confidence','bbox','semantic_type','review_status'])<>'{}'::jsonb
      or not(item ?& array['text','confidence','bbox','semantic_type','review_status']) or jsonb_typeof(item->'text')<>'string' or length(item->>'text')>2000
      or jsonb_typeof(item->'confidence')<>'number' or (item->>'confidence')::numeric not between 0 and 1
      or jsonb_typeof(item->'bbox')<>'array' or jsonb_array_length(item->'bbox')<>4
      or item->>'semantic_type' is distinct from 'unclassified' or item->>'review_status' is distinct from 'unreviewed' then return jsonb_build_object('error','invalid_evidence');end if;
     if exists(select from jsonb_array_elements(item->'bbox')q where jsonb_typeof(q)<>'number') then return jsonb_build_object('error','invalid_evidence');end if;
     if exists(select from jsonb_array_elements(item->'bbox')q where (q#>>'{}')::numeric not between 0 and 1) then return jsonb_build_object('error','invalid_evidence');end if;
    end loop;
   end if;
  end if;
  digest:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
  select id,evidence_hash into evidence_id,bodyhash from crowd_kol.evidence where owner=u and platform=v_mode and content_id=cid and kind=act and asset_sha256=e->>'asset_sha256';
  if evidence_id is not null then
   if bodyhash<>digest then return jsonb_build_object('error','evidence_reused');end if;
  else
   insert into crowd_kol.evidence(owner,platform,content_id,kind,authorization_ref,asset_sha256,evidence_hash,evidence)
    values(u,v_mode,cid,act,p_payload->>'authorization_ref',e->>'asset_sha256',digest,e) returning id into evidence_id;
  end if;
  return jsonb_build_object('evidence_id',evidence_id,'verification','user_declared_not_independently_verified');
 elsif p_action='detail' then
  cid:=p_payload->>'content_id';v_mode:=p_payload->>'platform';
  select * into content from crowd_kol.contents c where c.owner=u and c.platform=v_mode and c.content_id=cid;
  if content.content_id is null then return jsonb_build_object('error','content_missing');end if;
  return jsonb_build_object('content',to_jsonb(content)-'owner'-'content_hash',
   'evidence',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'-'evidence_hash'),'[]'::jsonb) from (select * from crowd_kol.evidence where owner=u and platform=v_mode and content_id=cid order by created_at desc limit 100)v),
   'versions',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'),'[]'::jsonb) from (select * from crowd_kol.versions where owner=u and platform=v_mode and content_id=cid order by version desc limit 100)v),
   'metric_snapshots',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'),'[]'::jsonb) from (select * from crowd_kol.snapshots where owner=u and platform=v_mode and content_id=cid order by received_at desc limit 100)v),
   'comment_entities',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'-'body_hash'),'[]'::jsonb) from (select * from crowd_kol.comment_entities where owner=u and platform=v_mode and content_id=cid order by last_seen_at desc limit 200)v),
   'comment_versions',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'),'[]'::jsonb) from (select * from crowd_kol.comment_versions where owner=u and platform=v_mode and content_id=cid order by created_at desc limit 200)v),
   'comments',(select coalesce(jsonb_agg(to_jsonb(v)-'owner'),'[]'::jsonb) from (select c.* from crowd_kol.comments c join crowd_kol.snapshots sn on sn.owner=c.owner and sn.request=c.request where c.owner=u and sn.platform=v_mode and sn.content_id=cid order by sn.received_at desc,c.item_key limit 200)v));
 elsif p_action='delete_content' then
  delete from crowd_kol.contents c where c.owner=u and c.platform=p_payload->>'platform' and c.content_id=p_payload->>'content_id';
  return jsonb_build_object('deleted',true);
 elsif p_action in ('list','export') then
  maxn:=case when p_action='list' then 30 else coalesce((p_payload->>'limit')::int,100) end;
  if maxn not between 1 and 500 then return jsonb_build_object('error','invalid_limit');end if;
  if p_payload ? 'target_id' then
   select * into target from crowd_kol.targets t where t.owner=u and t.id=(p_payload->>'target_id')::uuid;
   if target.id is null then return jsonb_build_object('error','target_missing');end if;
  end if;
  result:=jsonb_build_object('contents',(select coalesce(jsonb_agg(q.doc),'[]'::jsonb) from (
   select to_jsonb(c)-'owner'-'content_hash'-'latest_record'||jsonb_build_object('comments',c.latest_record#>'{extra,comments}','field_observations',c.latest_record#>'{extra,field_observations}','content_type',c.latest_record#>'{extra,content_type}','source_kind','rendered_public_dom') as doc from crowd_kol.contents c
   where c.owner=u and (target.id is null or c.platform=target.platform and (target.target_kind='content' and c.content_id=target.target_id or target.target_kind='creator' and c.creator_id=target.target_id)) order by c.last_seen_at desc limit maxn)q),
   'tasks',(select coalesce(jsonb_agg(q.doc),'[]'::jsonb) from (select to_jsonb(t)-'owner'-'bridge_task' as doc from crowd_kol.tasks t where t.owner=u and (target.id is null or t.target_ref=target.id) order by t.created_at desc limit 100)q),
   'coverage','observed_only');
  if p_action='list' then result:=result||jsonb_build_object('credential_epoch',epoch,'principal_bindings',bindings,'profiles',(select coalesce(jsonb_agg(to_jsonb(q)-'owner'),'[]'::jsonb) from (select distinct on (target_ref) * from crowd_kol.profiles where owner=u order by target_ref,received_at desc)q),'targets',(select coalesce(jsonb_agg(to_jsonb(t)-'owner'),'[]'::jsonb) from crowd_kol.targets t where t.owner=u and t.status<>'deleted'),
   'capabilities',jsonb_build_object('platforms',jsonb_build_array('xiaohongshu','bilibili'),'max_items',10,'max_comments',20,'include_replies',true,'reply_expansion_platforms',jsonb_build_array('xiaohongshu')));end if;
  return result;
 end if;
 return jsonb_build_object('error','invalid_action');
exception when invalid_text_representation or datetime_field_overflow or invalid_datetime_format or numeric_value_out_of_range then return jsonb_build_object('error','invalid_payload');
end $$;

-- Shared participant lock serializes dispatch, checkpoint, handoff and the existing safety guard.
create or replace function public.crowd_v4_kol(p_action text,p_payload jsonb default '{}') returns jsonb
language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();p crowd_v4.participants;t crowd_kol.tasks;target crowd_kol.targets;
 r jsonb;cp jsonb;ids jsonb;v jsonb;binding jsonb;epoch bigint;executor uuid;req uuid;hash text;attempt crowd_kol.source_attempts;
 cid text;revision int;scrolls int;pages int;found_task uuid;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' or p.consent is distinct from 'crowd-public-v4' then raise exception 'approval_required' using errcode='42501';end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or octet_length(p_payload::text)>200000 then return jsonb_build_object('error','invalid_payload');end if;
 executor:=(p_payload->>'executor_id')::uuid;
 if p_action='start' then
  scrolls:=coalesce((p_payload->>'max_discovery_scrolls')::int,case when p_payload->>'mode'='history' then 30 else 3 end);
  pages:=coalesce((p_payload->>'max_comment_pages')::int,1);
  if scrolls not between 1 and (case when p_payload->>'mode'='history' then 30 else 3 end) or pages not between 1 and 5 then return jsonb_build_object('error','invalid_task_limits');end if;
  if p_payload->>'mode'='periodic' and coalesce((p_payload->>'window_days')::int,30)*1440<2880+coalesce((p_payload->>'interval_minutes')::int,60) then return jsonb_build_object('error','invalid_overlap_window','required_window_days',ceil((2880+coalesce((p_payload->>'interval_minutes')::int,60))/1440.0));end if;
  r:=crowd_kol.rpc_base(p_action,p_payload);
  if r ? 'error' then return r;end if;
  if r->'task' is null or r->'task'='null'::jsonb then select scan_block_reason into cid from crowd_kol.targets where owner=u and id=(p_payload->>'target_id')::uuid;return jsonb_build_object('error',coalesce(cid,'scan_window_blocked'));end if;
  update crowd_kol.targets set max_discovery_scrolls=scrolls,max_comment_pages=pages where owner=u and id=(r->'task'->>'target_ref')::uuid;
  update crowd_kol.tasks set max_discovery_scrolls=scrolls,max_comment_pages=pages where owner=u and id=(r->'task'->>'id')::uuid and state='queued' returning * into t;
  if t.id is not null then r:=jsonb_build_object('task',to_jsonb(t)-'owner'-'bridge_task');end if;
  return r;
 elsif p_action='claim' then
  if exists(select from crowd_kol.source_attempts a join crowd_kol.tasks z on z.owner=a.owner and z.id=a.task where a.owner=u and a.state='unknown' and z.state<>'running') then return jsonb_build_object('task',null,'reason','source_outcome_unknown');end if;
  select * into t from crowd_kol.tasks where owner=u and state='running' order by created_at limit 1 for update;
  if t.id is not null then
   if t.execution_protocol=1 and (executor is distinct from t.executor_id or t.released_at is not null) then return jsonb_build_object('task',null,'reason',case when t.released_at is not null then 'explicit_recovery_required' else 'old_executor_required' end);end if;
   if t.execution_protocol=0 and executor is not null and t.attempts<>'{"search":0,"detail":0,"scroll":0,"comment":0}'::jsonb then return jsonb_build_object('task',null,'reason','legacy_executor_required');end if;
   if t.execution_protocol=1 and t.lease_until<=clock_timestamp() then return jsonb_build_object('task',null,'reason','lease_expired_requires_release');end if;
  end if;
  r:=crowd_kol.rpc_base(p_action,p_payload-'executor_id');
  if r->'task' is null or r->'task'='null'::jsonb then select scan_block_reason into cid from crowd_kol.targets where owner=u and status='active' and scan_block_reason is not null order by updated_at limit 1;return case when cid is null then r else r||jsonb_build_object('reason',cid) end;end if;
  if executor is not null then
   update crowd_kol.tasks set executor_id=executor,execution_protocol=1 where owner=u and id=(r->'task'->>'id')::uuid and (executor_id is null or executor_id=executor) returning * into t;
   if t.id is null then return jsonb_build_object('task',null,'reason','old_executor_required');end if;
   r:=jsonb_set(r,'{task}',r->'task'||jsonb_build_object('executor_id',executor,'execution_protocol',1,'checkpoint',t.checkpoint));
  end if;
  return r;
 elsif p_action in ('submit','profile') then
  r:=crowd_kol.rpc_base(p_action,p_payload);
  if r->>'gate'='received' then update crowd_kol.source_attempts set state=case when p_action='submit' then 'received' else 'observed' end,settled_at=coalesce(settled_at,clock_timestamp()) where owner=u and admission_id=(p_payload->>'admission_id')::uuid;end if;
  return r;
 elsif p_action in ('guard','finish','checkpoint','action_settle','release','recover','recovery_status') then
  select * into t from crowd_kol.tasks where owner=u and id=(p_payload->>'task')::uuid for update;
  if t.id is null then if p_action='guard' then return jsonb_build_object('allowed',false,'reason','lease_expired','wait_ms',0);end if;return jsonb_build_object('error','task_missing');end if;
  if t.execution_protocol=0 then
   if p_action in ('guard','finish') then return crowd_kol.rpc_base(p_action,p_payload);end if;
   return jsonb_build_object('error','legacy_executor_required');
  end if;
  select * into target from crowd_kol.targets where owner=u and id=t.target_ref;
  select credential_epoch,principal_bindings->target.platform into epoch,binding from crowd_kol.settings where owner=u;
  if p_action='recovery_status' then
   return jsonb_build_object('task',to_jsonb(t)-'owner'-'bridge_task','unsettled',(select coalesce(jsonb_agg(jsonb_build_object('admission_id',a.admission_id,'action',a.action,'content_id',a.content_id,'state',a.state,'failure_reason',a.failure_reason)),'[]'::jsonb) from crowd_kol.source_attempts a where owner=u and task=t.id and state='unknown'),'source_coverage','unverified','old_outbox_drain',case when t.released_at is null then 'unverified' else 'original_executor_declared_drained' end);
  elsif p_action='recover' then
   if executor is null or (t.released_at is null and not(executor=t.executor_id and t.recovered_at is not null)) then return jsonb_build_object('error','old_executor_required');end if;
   if t.state not in ('running','partial') or (t.state='partial' and t.reason is distinct from 'lease_expired') or target.status<>'active' or t.credential_epoch<>epoch then return jsonb_build_object('error','recovery_not_active');end if;
   if t.principal_ref is null or t.principal_ref is distinct from (binding->>'principal_ref') then return jsonb_build_object('error','identity_verification_required');end if;
   if exists(select from crowd_kol.source_attempts where owner=u and task=t.id and state='unknown') then return jsonb_build_object('error','source_outcome_unknown');end if;
   if t.released_at is not null then
    update crowd_kol.tasks set executor_id=executor,released_at=null,recovered_at=clock_timestamp(),state='running',reason=null,lease_until=clock_timestamp()+interval '20 minutes' where owner=u and id=t.id returning * into t;
   end if;
   return jsonb_build_object('task',(to_jsonb(t)-'owner'-'bridge_task')||jsonb_build_object('platform',target.platform,'target_kind',target.target_kind,'target_id',target.target_id,'url',target.url,'include_replies',t.comment_depth=2,'known_ids',t.checkpoint->'processed_ids','refresh_ids','[]'::jsonb),'source_coverage','unverified');
  end if;
  if executor is null or executor is distinct from t.executor_id or t.lease_token is distinct from (p_payload->>'lease')::uuid then return jsonb_build_object('error','executor_mismatch');end if;
  if p_action='guard' then
   if t.released_at is not null then return jsonb_build_object('allowed',false,'reason','executor_released','wait_ms',0);end if;
   req:=(p_payload->>'request')::uuid;
   if req is null then return jsonb_build_object('error','request_required');end if;
   hash:=encode(sha256(convert_to((p_payload-'request')::text,'UTF8')),'hex');
   select * into attempt from crowd_kol.source_attempts where owner=u and request=req;
   if attempt.request is not null then
    if attempt.payload_hash<>hash then return jsonb_build_object('error','request_reused');end if;
    return attempt.result||jsonb_build_object('allowed',false,'replay',true,'reason','source_outcome_unknown','wait_ms',0,'attempt_state',attempt.state);
   end if;
   if p_payload->>'action'='comment' and (select count(*) from crowd_kol.source_attempts where owner=u and task=t.id and action='comment' and content_id=p_payload->>'content_id')>=t.max_comment_pages then return jsonb_build_object('allowed',false,'reason','comment_page_budget','wait_ms',0);end if;
   if p_payload->>'action'='detail' and exists(select from crowd_kol.snapshots where owner=u and task=t.id and content_id=p_payload->>'content_id') then return jsonb_build_object('allowed',false,'reason','content_already_received','wait_ms',0);end if;
   if exists(select from crowd_kol.source_attempts a where owner=u and task=t.id and state='unknown' and (a.action=p_payload->>'action' or a.action in ('search','scroll') or (a.action='detail' and p_payload->>'action'<>'comment'))) then return jsonb_build_object('allowed',false,'reason','source_outcome_unknown','wait_ms',0);end if;
   r:=crowd_kol.rpc_base(p_action,p_payload-array['executor_id','request']);
   if r->>'allowed'='true' then insert into crowd_kol.source_attempts(owner,request,task,executor_id,payload_hash,admission_id,action,content_id,result) values(u,req,t.id,executor,hash,(r->>'admission_id')::uuid,p_payload->>'action',p_payload->>'content_id',r);end if;
   return r;
  elsif p_action='action_settle' then
   select * into attempt from crowd_kol.source_attempts where owner=u and task=t.id and admission_id=(p_payload->>'admission_id')::uuid;
   if attempt.request is null or attempt.executor_id<>executor then return jsonb_build_object('error','admission_missing');end if;
   if p_payload->>'outcome' is null or p_payload->>'outcome' not in ('observed','failed') or (attempt.action='detail' and p_payload->>'outcome'='observed') then return jsonb_build_object('error','invalid_outcome');end if;
   if p_payload ? 'failure_reason' and (p_payload->>'outcome'<>'failed' or p_payload->>'failure_reason' is null or p_payload->>'failure_reason' not in ('source_not_found','source_private','source_deleted','parser_paused')) then return jsonb_build_object('error','invalid_outcome');end if;
   if attempt.state='unknown' then update crowd_kol.source_attempts set state=p_payload->>'outcome',failure_reason=p_payload->>'failure_reason',settled_at=clock_timestamp() where owner=u and request=attempt.request returning * into attempt;
   elsif attempt.state<>p_payload->>'outcome' or attempt.failure_reason is distinct from (p_payload->>'failure_reason') then return jsonb_build_object('error','outcome_conflict');end if;
   return jsonb_build_object('settled',true,'admission_id',attempt.admission_id,'state',attempt.state);
  elsif p_action='checkpoint' then
   if t.released_at is not null then return jsonb_build_object('error','executor_released');end if;
   if (p_payload-array['task','lease','executor_id','expected_revision','candidate_ids','processed_ids','scrolls','coverage'])<>'{}'::jsonb then return jsonb_build_object('error','invalid_checkpoint');end if;
   revision:=(p_payload->>'expected_revision')::int;scrolls:=(p_payload->>'scrolls')::int;
   if revision is null or scrolls is null or scrolls<coalesce((t.checkpoint->>'scrolls')::int,0) or scrolls>t.max_discovery_scrolls or scrolls>coalesce((t.attempts->>'scroll')::int,0) or p_payload->>'coverage' is null or p_payload->>'coverage' not in ('partial','observed_only') then return jsonb_build_object('error','invalid_checkpoint');end if;
   foreach cid in array array['candidate_ids','processed_ids'] loop
    ids:=p_payload->cid;
    if jsonb_typeof(ids) is distinct from 'array' or jsonb_array_length(ids)>100 then return jsonb_build_object('error','invalid_checkpoint');end if;
    if (select count(*) from jsonb_array_elements(ids))<>(select count(distinct value) from jsonb_array_elements(ids)) then return jsonb_build_object('error','invalid_checkpoint');end if;
    for v in select value from jsonb_array_elements(ids) loop
     if jsonb_typeof(v)<>'string' or (target.platform='xiaohongshu' and v#>>'{}' !~ '^[a-f0-9]{24}$') or (target.platform='bilibili' and v#>>'{}' !~ '^BV[0-9A-Za-z]{10}$') then return jsonb_build_object('error','invalid_checkpoint');end if;
    end loop;
   end loop;
   if exists(select from jsonb_array_elements_text(p_payload->'processed_ids') q(id) where not exists(select from crowd_kol.snapshots s where s.owner=u and s.task=t.id and s.content_id=q.id)) then return jsonb_build_object('error','receipt_missing');end if;
   if not ((p_payload->'processed_ids') @> (t.checkpoint->'processed_ids')) then return jsonb_build_object('error','checkpoint_regression');end if;
   if exists(select from jsonb_array_elements_text(t.checkpoint->'candidate_ids') q(id) where not (p_payload->'candidate_ids' ? q.id) and not (p_payload->'processed_ids' ? q.id) and not exists(select from crowd_kol.source_attempts a where owner=u and task=t.id and content_id=q.id and action='detail' and state='failed')) then return jsonb_build_object('error','checkpoint_gap');end if;
   cp:=jsonb_build_object('revision',revision+1,'candidate_ids',p_payload->'candidate_ids','processed_ids',p_payload->'processed_ids','scrolls',scrolls,'coverage',p_payload->>'coverage');
   if (t.checkpoint->>'revision')::int=revision+1 and t.checkpoint=cp then return jsonb_build_object('checkpoint',t.checkpoint,'replay',true);end if;
   if (t.checkpoint->>'revision')::int<>revision then return jsonb_build_object('error','checkpoint_conflict','checkpoint',t.checkpoint);end if;
   update crowd_kol.tasks set checkpoint=cp where owner=u and id=t.id;
   return jsonb_build_object('checkpoint',cp);
  elsif p_action='release' then
   if (p_payload->>'checkpoint_revision')::int is distinct from (t.checkpoint->>'revision')::int or p_payload->'outbox_drained' is distinct from 'true'::jsonb then return jsonb_build_object('error','outbox_not_drained');end if;
   if exists(select from crowd_kol.source_attempts where owner=u and task=t.id and state='unknown') then return jsonb_build_object('error','source_outcome_unknown');end if;
   if exists(select from crowd_kol.snapshots s where s.owner=u and s.task=t.id and not (t.checkpoint->'processed_ids' ? s.content_id)) then return jsonb_build_object('error','checkpoint_missing_receipts');end if;
   if (t.checkpoint->>'revision')::int=0 then return jsonb_build_object('error','checkpoint_required');end if;
   update crowd_kol.tasks set released_at=coalesce(released_at,clock_timestamp()) where owner=u and id=t.id;
   return jsonb_build_object('released',true,'task',t.id,'checkpoint',t.checkpoint,'source_coverage','unverified');
  else
   if t.released_at is not null then return jsonb_build_object('error','executor_released');end if;
   return crowd_kol.rpc_base(p_action,p_payload-'executor_id');
  end if;
 end if;
 return crowd_kol.rpc_base(p_action,p_payload);
exception when invalid_text_representation or numeric_value_out_of_range then return jsonb_build_object('error','invalid_payload');
end $$;
revoke all on function crowd_kol.rpc_base(text,jsonb) from public,anon,authenticated;
revoke all on function public.crowd_v4_kol(text,jsonb) from public,anon;
grant execute on function public.crowd_v4_kol(text,jsonb) to authenticated;
notify pgrst,'reload schema';
commit;
