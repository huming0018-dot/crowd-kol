begin;
create schema crowd_kol;
revoke all on schema crowd_kol from public,anon,authenticated;
create table crowd_kol.settings(owner uuid primary key references crowd_v4.participants(user_id),credential_epoch bigint not null default 1,principal_bindings jsonb not null default '{}');
create table crowd_kol.targets(
 owner uuid not null references crowd_v4.participants(user_id),id uuid not null default gen_random_uuid(),
 platform text not null check(platform in ('xiaohongshu','bilibili')),target_kind text not null check(target_kind in ('creator','content')),
 target_id text not null,url text not null,label text not null default '',"group" text not null default '',status text not null default 'active' check(status in ('active','paused','deleted')),
 max_items int not null default 2 check(max_items between 1 and 10),comment_limit int not null default 0 check(comment_limit between 0 and 20),
 comment_depth int not null default 1 check(comment_depth in (1,2)),window_days int not null default 30 check(window_days between 1 and 3650),
 interval_minutes int not null default 0 check(interval_minutes=0 or interval_minutes between 60 and 10080),next_due_at timestamptz,
 created_at timestamptz not null default clock_timestamp(),updated_at timestamptz not null default clock_timestamp(),
 primary key(owner,id),unique(owner,platform,target_kind,target_id));
create table crowd_kol.tasks(
 owner uuid not null,id uuid not null default gen_random_uuid(),target_ref uuid not null,bridge_task bigint not null references crowd_v4.tasks(id),
 mode text not null check(mode in ('manual','history','periodic')),state text not null default 'queued' check(state in ('queued','running','completed','partial','auth_required','risk_paused','cancelled','error')),
 reason text,max_items int not null default 2 check(max_items between 1 and 10),comment_limit int not null default 0 check(comment_limit between 0 and 20),
 comment_depth int not null default 1 check(comment_depth in (1,2)),window_days int not null default 30 check(window_days between 1 and 3650),credential_epoch bigint not null,principal_ref text,principal_verification text not null default 'unverified',principal_verification_at timestamptz,lease_token uuid,lease_until timestamptz,
 attempts jsonb not null default '{"search":0,"detail":0,"scroll":0,"comment":0}',received int not null default 0,
 created_at timestamptz not null default clock_timestamp(),finished_at timestamptz,
 primary key(owner,id),foreign key(owner,target_ref) references crowd_kol.targets(owner,id));
create index kol_task_queue on crowd_kol.tasks(owner,state,created_at);
create table crowd_kol.admissions(
 owner uuid not null,id uuid not null default gen_random_uuid(),task uuid not null,lease uuid not null,action text not null,
 content_id text,issued_at timestamptz not null default clock_timestamp(),accept_until timestamptz not null default clock_timestamp()+interval '24 hours',
 used_request uuid,primary key(owner,id),foreign key(owner,task) references crowd_kol.tasks(owner,id));
create table crowd_kol.contents(
 owner uuid not null,platform text not null,content_id text not null,creator_id text,url text not null,title text not null,body text not null,
 published_at text,metrics jsonb not null,version int not null,content_hash text not null,latest_record jsonb not null,
 first_seen_at timestamptz not null default clock_timestamp(),last_seen_at timestamptz not null default clock_timestamp(),
 primary key(owner,platform,content_id));
create table crowd_kol.versions(
 owner uuid not null,platform text not null,content_id text not null,version int not null,record jsonb not null,created_at timestamptz not null default clock_timestamp(),
 primary key(owner,platform,content_id,version),foreign key(owner,platform,content_id) references crowd_kol.contents on delete cascade);
create table crowd_kol.snapshots(
 owner uuid not null,request uuid not null,task uuid not null,platform text not null,content_id text not null,metrics jsonb not null,
 captured_at timestamptz not null,received_at timestamptz not null default clock_timestamp(),primary key(owner,request),
 foreign key(owner,platform,content_id) references crowd_kol.contents on delete cascade,foreign key(owner,task) references crowd_kol.tasks);
create table crowd_kol.comments(
 owner uuid not null,request uuid not null,item_key text not null,parent_key text,body text not null,truncated boolean not null,record jsonb not null,
 primary key(owner,request,item_key),foreign key(owner,request) references crowd_kol.snapshots on delete cascade);
create table crowd_kol.comment_entities(
 owner uuid not null,platform text not null,content_id text not null,comment_id text not null,
 parent_comment_id text,root_comment_id text,relationship_status text not null check(relationship_status in ('root','parent_observed','orphan','unknown')),
 is_reply boolean,body text not null,truncated boolean not null,like_count bigint,like_label text,published_label text,
 version int not null,body_hash text not null,latest_request uuid not null,first_seen_at timestamptz not null default clock_timestamp(),last_seen_at timestamptz not null default clock_timestamp(),
 primary key(owner,platform,content_id,comment_id),foreign key(owner,platform,content_id) references crowd_kol.contents on delete cascade);
create table crowd_kol.comment_versions(
 owner uuid not null,platform text not null,content_id text not null,comment_id text not null,version int not null,request uuid not null,record jsonb not null,
 created_at timestamptz not null default clock_timestamp(),primary key(owner,platform,content_id,comment_id,version),
 foreign key(owner,platform,content_id,comment_id) references crowd_kol.comment_entities on delete cascade);
create table crowd_kol.profiles(
 owner uuid not null,request uuid not null,target_ref uuid not null,platform text not null,author_id text not null,profile jsonb not null,received_at timestamptz not null default clock_timestamp(),
 primary key(owner,request),foreign key(owner,target_ref) references crowd_kol.targets);
create table crowd_kol.evidence(
 owner uuid not null,id uuid not null default gen_random_uuid(),platform text not null,content_id text not null,kind text not null,authorization_ref text not null,
 asset_sha256 text not null,evidence_hash text not null,evidence jsonb not null,verification text not null default 'user_declared_not_independently_verified',created_at timestamptz not null default clock_timestamp(),
 primary key(owner,id),unique(owner,platform,content_id,kind,asset_sha256),foreign key(owner,platform,content_id) references crowd_kol.contents on delete cascade);
create table crowd_kol.receipts(
 owner uuid not null,request uuid not null,payload_hash text not null,result jsonb not null,created_at timestamptz not null default clock_timestamp(),primary key(owner,request));
do $$declare tab text;begin
 foreach tab in array array['settings','targets','tasks','admissions','contents','versions','snapshots','comments','comment_entities','comment_versions','profiles','evidence','receipts'] loop
  execute format('alter table crowd_kol.%I enable row level security',tab);
  execute format('revoke all on crowd_kol.%I from public,anon,authenticated',tab);
 end loop;
end $$;

create function crowd_kol.normalize_url(p_url text) returns jsonb language plpgsql immutable set search_path='' as $$
declare clean text; hit text[];begin
 if p_url is null or length(p_url)>2048 or p_url ~ '[[:space:]\\]' then raise exception 'invalid_target_url';end if;
 clean:=regexp_replace(p_url,'[?#].*$','');clean:=regexp_replace(clean,'/$','');
 hit:=regexp_match(clean,'^https://(www\.)?xiaohongshu\.com/(user/profile|explore|discovery/item)/([a-f0-9]{24})$');
 if hit is not null then return jsonb_build_object('platform','xiaohongshu','target_kind',case when hit[2]='user/profile' then 'creator' else 'content' end,
 'target_id',hit[3],'url','https://www.xiaohongshu.com/'||case when hit[2]='user/profile' then 'user/profile/' else 'explore/' end||hit[3]);end if;
 hit:=regexp_match(clean,'^https://space\.bilibili\.com/([1-9][0-9]{0,19})$');
 if hit is not null then return jsonb_build_object('platform','bilibili','target_kind','creator','target_id',hit[1],'url','https://space.bilibili.com/'||hit[1]);end if;
 hit:=regexp_match(clean,'^https://(www\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10})$');
 if hit is not null then return jsonb_build_object('platform','bilibili','target_kind','content','target_id',hit[2],'url','https://www.bilibili.com/video/'||hit[2]);end if;
 raise exception 'unsupported_target_url';end $$;

create function crowd_kol.enqueue(u uuid,target uuid,mode text,max_items int,comments int,days int) returns crowd_kol.tasks language plpgsql set search_path='' as $$
declare t crowd_kol.targets;r crowd_kol.tasks;b bigint;epoch bigint;binding jsonb;begin
 select * into t from crowd_kol.targets where owner=u and id=target and status='active' for update;
 if t.id is null then raise exception 'target_not_active';end if;
 select * into r from crowd_kol.tasks where owner=u and target_ref=target and state in ('queued','running') order by created_at limit 1;
 if r.id is not null then return r;end if;
 select credential_epoch,principal_bindings->t.platform into epoch,binding from crowd_kol.settings where owner=u;
 insert into crowd_v4.tasks(source_key,query,anchor_terms,target,status) values('kol:'||gen_random_uuid(),'KOL '||t.platform,'["KOL"]',max_items,'closed') returning id into b;
 insert into crowd_kol.tasks(owner,target_ref,bridge_task,mode,max_items,comment_limit,window_days,comment_depth,credential_epoch,principal_ref,principal_verification,principal_verification_at)
 values(u,target,b,mode,max_items,comments,days,t.comment_depth,epoch,binding->>'principal_ref',coalesce(binding->>'verification','unverified'),(binding->>'verification_at')::timestamptz) returning * into r;
 update crowd_kol.targets set next_due_at=case when interval_minutes>0 then clock_timestamp()+make_interval(mins=>interval_minutes) else null end where owner=u and id=target;
 return r;end $$;

create function public.crowd_v4_kol(p_action text,p_payload jsonb default '{}'::jsonb) returns jsonb
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
  maxn:=case act when 'detail' then task.max_items when 'search' then 1 when 'scroll' then 3 else case when task.comment_limit>0 then task.max_items else 0 end end;
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
   or (x-array['author','author_opinion_quotes','comments','media_present','field_observations','metric_labels','published_label','hashtags','content_type','comment_status','replies_status'])<>'{}'::jsonb
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
   if (s->>'published_at')::date<(task.created_at at time zone 'Asia/Shanghai')::date-task.window_days then return jsonb_build_object('error','outside_window');end if;
  end if;
  -- Allow ordinary public links in prose, never serialized credential assignments.
  if result::text ~* '(https?://[^[:space:]]*[?&#](xsec_token|access_token|refresh_token|authorization|cookie|password|token)=|https?://[^/@[:space:]]+@)'
   then return jsonb_build_object('error','credential_material');end if;
  if x ? 'comments' then
   item:=x->'comments';
   if jsonb_typeof(item)<>'object' or (item-array['items','coverage','complete','truncated','captured_count','panel_found','loaded_count','omitted_count','more_available'])<>'{}'::jsonb or jsonb_typeof(item->'items') is distinct from 'array' or item->>'coverage' is distinct from 'visible_loaded_only' or item->>'complete' is distinct from 'false'
    or jsonb_typeof(item->'truncated') is distinct from 'boolean' or jsonb_array_length(item->'items')>task.comment_limit
    or item->>'captured_count' is distinct from jsonb_array_length(item->'items')::text then return jsonb_build_object('error','invalid_comments');end if;
   for item in select value from jsonb_array_elements(x#>'{comments,items}') loop
    if (item-array['key','comment_id','parent_key','is_reply','author_display','text','original_length','truncated','like_count','like_label','published_label'])<>'{}'::jsonb
     or coalesce(item->>'key','') !~ '^comment-[1-9][0-9]{0,2}$' or item->>'key'=any(seen)
     or (item->>'parent_key' is not null and (task.comment_depth<>2 or not(item->>'parent_key'=any(roots))))
     or jsonb_typeof(item->'text') is distinct from 'string' or length(item->>'text') not between 1 and 2000
     or coalesce(item->>'original_length','') !~ '^[0-9]{1,8}$' or jsonb_typeof(item->'truncated') is distinct from 'boolean'
     then return jsonb_build_object('error','invalid_comments');end if;
    if (item->>'original_length')::int<length(item->>'text') then return jsonb_build_object('error','invalid_comments');end if;
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
    select * into comment_entity from crowd_kol.comment_entities c where c.owner=u and c.platform=target.platform and c.content_id=cid and c.comment_id=comment_id_value for update;
    comment_version:=case when comment_entity.comment_id is null then 1 when comment_entity.body_hash=comment_hash then comment_entity.version else comment_entity.version+1 end;
    insert into crowd_kol.comment_entities(owner,platform,content_id,comment_id,parent_comment_id,root_comment_id,relationship_status,is_reply,body,truncated,like_count,like_label,published_label,version,body_hash,latest_request)
     values(u,target.platform,cid,comment_id_value,parent_id_value,root_id_value,relation,(item->>'is_reply')::boolean,item->>'text',(item->>'truncated')::boolean,(item->>'like_count')::bigint,item->>'like_label',item->>'published_label',comment_version,comment_hash,req)
     on conflict(owner,platform,content_id,comment_id) do update set parent_comment_id=excluded.parent_comment_id,root_comment_id=excluded.root_comment_id,relationship_status=excluded.relationship_status,is_reply=excluded.is_reply,
      body=excluded.body,truncated=excluded.truncated,like_count=excluded.like_count,like_label=excluded.like_label,published_label=excluded.published_label,version=excluded.version,body_hash=excluded.body_hash,latest_request=excluded.latest_request,last_seen_at=clock_timestamp();
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
  act:=p_payload->>'reason';if act not in ('completed','partial','auth_required','risk_paused','cancelled','error') or act is null then return jsonb_build_object('error','invalid_finish');end if;
  if task.state='running' and act='risk_paused' then
   v_mode:=coalesce(p_payload->>'risk_type','rate_limit');if v_mode not in ('captcha','rate_limit') then return jsonb_build_object('error','invalid_risk_type');end if;
   perform public.crowd_v4_guard(v_mode);
  end if;
  v_mode:=act;
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
   or (e ? 'processor' and (jsonb_typeof(e->'processor') is distinct from 'string' or e->>'processor' not in ('apple_speech_ondevice','manual_import','apple_vision')))
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
revoke all on all functions in schema crowd_kol from public,anon,authenticated;
revoke all on function public.crowd_v4_kol(text,jsonb) from public,anon;
grant execute on function public.crowd_v4_kol(text,jsonb) to authenticated;
notify pgrst,'reload schema';
commit;
