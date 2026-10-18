begin;
-- Private observations: independent from evidence verification and rewards.
create schema crowd_observation;
revoke all on schema crowd_observation from public,anon,authenticated;
create table crowd_observation.authors (
 author_id text primary key check(author_id ~ '^[a-f0-9]{24}$'), profile_url text not null,
 nickname text, first_seen timestamptz not null default now(), last_seen timestamptz not null default now()
);
create table crowd_observation.notes (
 note_id text primary key references crowd_v4.proofs(note_id),
 author_id text references crowd_observation.authors(author_id), base_record jsonb not null
);
create table crowd_observation.snapshots (
 request uuid primary key, user_id uuid not null references crowd_v4.participants(user_id),
 parent_request uuid not null, note_id text not null references crowd_observation.notes(note_id),
 kind text not null check(kind in ('base','note','profile')), data jsonb not null,
 captured_at timestamptz not null, received_at timestamptz not null default now(),
 unique(user_id,parent_request,kind)
);
create table crowd_observation.risk_signals (user_id uuid primary key references crowd_v4.participants(user_id),seen_at timestamptz not null default now());
create table crowd_observation.preferences (
 user_id uuid primary key references crowd_v4.participants(user_id), profiles boolean not null default false,
 updated_at timestamptz not null default now()
);
create table crowd_observation.profile_attempts (
 author_id text primary key references crowd_observation.authors(author_id), user_id uuid not null references crowd_v4.participants(user_id),
 parent_request uuid not null, token uuid not null default gen_random_uuid(), attempted_at timestamptz not null default now()
);
create table crowd_observation.receipts (
 user_id uuid not null references crowd_v4.participants(user_id), request uuid not null,
 parent_request uuid not null, kind text not null, data jsonb not null,result jsonb not null,
 primary key(user_id,request)
);
create index observation_snapshots_note on crowd_observation.snapshots(note_id,captured_at);
create index observation_snapshots_user on crowd_observation.snapshots(user_id);
create index observation_notes_author on crowd_observation.notes(author_id);
create index observation_attempts_user_time on crowd_observation.profile_attempts(user_id,attempted_at);
-- Persist all admitted attempts for the daily cap even when an author's cache row is replaced later.
create table crowd_observation.profile_budget (
 user_id uuid primary key references crowd_v4.participants(user_id), day date not null, attempts int not null default 0
);
do $$ declare tab text; begin
 foreach tab in array array['authors','notes','snapshots','preferences','profile_attempts','receipts','profile_budget','risk_signals'] loop
  execute format('alter table crowd_observation.%I enable row level security',tab);
  execute format('revoke all on crowd_observation.%I from public,anon,authenticated',tab);
 end loop;
end $$;

create function crowd_observation.validate_note(p_record jsonb,p_task bigint) returns jsonb
language plpgsql set search_path='' as $$
declare s jsonb; e jsonb; t crowd_v4.tasks; capture timestamptz; c jsonb; item jsonb; seen text[]:=array[]::text[];
begin
 select * into t from crowd_v4.tasks where id=p_task;
 s:=p_record->'standard'; e:=p_record->'evidence';
 if jsonb_typeof(p_record) is distinct from 'object' or p_record->>'schema_version' is distinct from '4'
 or jsonb_typeof(s) is distinct from 'object' or jsonb_typeof(e) is distinct from 'object' or jsonb_typeof(p_record->'extra') is distinct from 'object'
 or octet_length(p_record::text)>180000 or s->>'platform' is distinct from 'xiaohongshu'
 or coalesce(s->>'note_id','') !~ '^[a-f0-9]{24}$' or s->>'url' is distinct from ('https://www.xiaohongshu.com/explore/'||(s->>'note_id'))
 or jsonb_typeof(s->'title') is distinct from 'string' or length(s->>'title')>300
 or jsonb_typeof(e->'text') is distinct from 'string' or length(e->>'text')>24000 or (length(e->>'text')=0 and length(s->>'title')=0 and p_record->'extra'->>'media_present' is distinct from 'true')
 or e->>'source' is distinct from 'rendered_public_dom' then return jsonb_build_object('error','invalid_record'); end if;
 if not (s ?& array['platform','note_id','url','title','captured_at','published_at','author_display','like_count','collect_count','comment_count'])
 or jsonb_typeof(s->'author_display') not in ('string','null') or length(s->>'author_display')>100
 or jsonb_typeof(s->'published_at') not in ('string','null')
 or (s->>'published_at' is not null and s->>'published_at' !~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}$')
 or e->>'parser_version' is null or e->>'parser_version' !~ '^4\.[0-9]+\.[0-9]+$'
 or jsonb_typeof(e->'original_length') is distinct from 'number' or coalesce(e->>'original_length','') !~ '^[0-9]{1,8}$'
 or jsonb_typeof(e->'truncated') is distinct from 'boolean'
 or jsonb_typeof(p_record->'extra'->'author_opinion_quotes') is distinct from 'array'
 then return jsonb_build_object('error','invalid_record'); end if;
 if (e->>'original_length')::int<length(e->>'text') or jsonb_array_length(p_record->'extra'->'author_opinion_quotes')>30
 or exists(select 1 from jsonb_array_elements(p_record->'extra'->'author_opinion_quotes') q where jsonb_typeof(q)<>'string' or strpos(e->>'text',q#>>'{}')=0)
 or exists(select 1 from jsonb_each(s) a(key,value) where key in ('like_count','collect_count','comment_count','view_count') and
   (jsonb_typeof(value) not in ('null','number') or (value<>'null'::jsonb and value::text !~ '^[0-9]{1,10}$')))
 then return jsonb_build_object('error','invalid_record'); end if;
 if exists(select 1 from jsonb_each(s) a(key,value) where key in ('like_count','collect_count','comment_count','view_count') and value<>'null'::jsonb and value::text::numeric>2147483647)
 then return jsonb_build_object('error','invalid_record'); end if;
 begin perform (s->>'published_at')::date; exception when others then return jsonb_build_object('error','invalid_published_date'); end;
 begin capture:=(s->>'captured_at')::timestamptz; exception when others then return jsonb_build_object('error','invalid_timestamp'); end;
 if capture is null or capture>now()+interval '5 minutes' or capture<now()-interval '24 hours' then return jsonb_build_object('error','invalid_timestamp'); end if;
 if not exists(select 1 from jsonb_array_elements_text(t.anchor_terms) a(term) where length(term)>=2 and
 strpos(lower(regexp_replace((s->>'title')||' '||(e->>'text'),'[[:space:][:punct:]]','','g')),lower(regexp_replace(term,'[[:space:][:punct:]]','','g')))>0)
 then return jsonb_build_object('error','unrelated_note'); end if;

 if p_record->'extra'->'author' is not null and p_record->'extra'->'author'<>'null'::jsonb then
  if jsonb_typeof(p_record->'extra'->'author')<>'object'
   or coalesce(p_record#>>'{extra,author,id}','') !~ '^[a-f0-9]{24}$'
   or p_record#>>'{extra,author,url}' is distinct from ('https://www.xiaohongshu.com/user/profile/'||(p_record#>>'{extra,author,id}'))
  then return jsonb_build_object('error','invalid_record'); end if;
 end if;
 c:=p_record#>'{extra,comments}';
 if c is not null then
  if jsonb_typeof(c->'items') is distinct from 'array' or c->>'coverage' is distinct from 'visible_loaded_only'
   or c->>'complete' is distinct from 'false' or jsonb_typeof(c->'truncated') is distinct from 'boolean'
  then return jsonb_build_object('error','invalid_record'); end if;
  if jsonb_array_length(c->'items')>50 or c->>'captured_count' is distinct from jsonb_array_length(c->'items')::text then return jsonb_build_object('error','invalid_record'); end if;
  for item in select value from jsonb_array_elements(c->'items') loop
   if coalesce(item->>'key','') !~ '^comment-[1-9][0-9]*$' or item->>'key'=any(seen)
    or (item->>'parent_key' is not null and not(item->>'parent_key'=any(seen)))
    or jsonb_typeof(item->'text') is distinct from 'string' or length(item->>'text') not between 1 and 2000
    or coalesce(item->>'original_length','') !~ '^[0-9]{1,8}$'
    or jsonb_typeof(item->'truncated') is distinct from 'boolean'
   then return jsonb_build_object('error','invalid_record'); end if;
   if (item->>'original_length')::int<length(item->>'text') then return jsonb_build_object('error','invalid_record'); end if;
   seen:=array_append(seen,item->>'key');
  end loop;
 end if;
 return '{}'::jsonb;
end $$;
revoke all on function crowd_observation.validate_note(jsonb,bigint) from public,anon,authenticated;
-- Validate before the legacy insert, while keeping the original UUID receipt replay first.
do $$ declare def text; begin
 def:=pg_get_functiondef('public.crowd_v4_submit(uuid,bigint,uuid,jsonb)'::regprocedure);
 if strpos(def,'length(e->>''text'') not between 8 and 24000')=0 then raise exception 'submit_anchor_missing'; end if;
 def:=replace(def,'length(e->>''text'') not between 8 and 24000','length(e->>''text'')>24000');
 def:=replace(def,' s:=p_record->''standard'';',' result:=crowd_observation.validate_note(p_record,p_task); if result ? ''error'' then return result; end if; s:=p_record->''standard'';');
 execute def;
end $$;

create function crowd_observation.project_base() returns trigger language plpgsql security definer set search_path='' as $$
declare f crowd_v4.proofs; a text;
begin
 if new.result->>'inserted' is distinct from 'true' then return new; end if;
 select * into f from crowd_v4.proofs where note_id=new.payload#>>'{record,standard,note_id}' and user_id=new.user_id;
 if f.id is null then return new; end if;
 a:=f.record#>>'{extra,author,id}';
 if a is not null then
  insert into crowd_observation.authors(author_id,profile_url,nickname) values(a,'https://www.xiaohongshu.com/user/profile/'||a,f.record#>>'{standard,author_display}')
   on conflict(author_id) do update set last_seen=now(),nickname=coalesce(excluded.nickname,crowd_observation.authors.nickname);
 end if;
 insert into crowd_observation.notes(note_id,author_id,base_record) values(f.note_id,a,f.record) on conflict do nothing;
 insert into crowd_observation.snapshots(request,user_id,parent_request,note_id,kind,data,captured_at)
 values(new.request,new.user_id,new.request,f.note_id,'base',f.record,(f.record#>>'{standard,captured_at}')::timestamptz) on conflict do nothing;
 return new;
end $$;
revoke all on function crowd_observation.project_base() from public,anon,authenticated;
create trigger crowd_observation_base after insert on crowd_v4.receipts for each row execute function crowd_observation.project_base();

create function public.crowd_v4_observation_preferences(p_profiles boolean) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 perform 1 from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4' for update;
 if not found then raise exception 'approval_required' using errcode='42501'; end if;
 if p_profiles is null then raise exception 'invalid_request'; end if;
 insert into crowd_observation.preferences(user_id,profiles) values(u,p_profiles) on conflict(user_id) do update set profiles=excluded.profiles,updated_at=now();
 return jsonb_build_object('profiles',p_profiles);
end $$;

-- One guard controls all actions. Profile visits use the existing detail cap and shared session/gap.
-- They can only be admitted through profile_claim, which supplies a previously received note ID.
do $$ declare def text; begin
 def:=pg_get_functiondef('public.crowd_v4_guard(text,bigint,text)'::regprocedure);
 def:=replace(def,'admitted boolean:=false;', 'action_key text; admitted boolean:=false;');
 def:=replace(def,$s$('control','search','detail','comment','scroll','captcha','rate_limit')$s$,$s$('control','search','detail','comment','scroll','captcha','rate_limit','profile')$s$);
 def:=replace(def,$s$('search','detail','comment','scroll')$s$,$s$('search','detail','comment','scroll','profile')$s$);
 def:=replace(def,' -- One identity', ' action_key:=case when p_action=''profile'' then ''detail'' else p_action end;
 -- One identity');
 def:=replace(def,'s.counts->>p_action','s.counts->>action_key'); def:=replace(def,'caps->>p_action','caps->>action_key'); def:=replace(def,'array[p_action]','array[action_key]');
 def:=replace(def,$s$if p_action='detail' then$s$, $s$if p_action='profile' and not exists(select from crowd_observation.profile_attempts a join crowd_observation.notes n using(author_id) where a.user_id=u and n.note_id=p_note and a.attempted_at>t-interval '1 minute') then raise exception 'profile_not_admitted'; end if; if p_action='detail' then$s$);
 def:=replace(def,$s$result:=jsonb_build_object('version'$s$, $s$result:=jsonb_build_object('observations',1,'version'$s$);
 execute def;
end $$;

alter function public.crowd_v4_guard(text,bigint,text) set schema crowd_observation;
alter function crowd_observation.crowd_v4_guard(text,bigint,text) rename to guard_internal;
revoke all on function crowd_observation.guard_internal(text,bigint,text) from public,anon,authenticated;
create function public.crowd_v4_guard(p_action text default 'control',p_task bigint default null,p_note text default null)
returns jsonb language plpgsql security definer set search_path='' as $$ declare result jsonb; begin
 if p_action='profile' then raise exception 'invalid_action';end if;
 result:=crowd_observation.guard_internal(p_action,p_task,p_note);
 if p_action='rate_limit' then
  perform 1 from crowd_v4.policy where singleton for update;
  insert into crowd_observation.risk_signals(user_id) values(auth.uid()) on conflict(user_id) do update set seen_at=now();
  delete from crowd_observation.risk_signals where seen_at<now()-interval '24 hours';
  if (select count(*) from crowd_observation.risk_signals where seen_at>now()-interval '10 minutes')>=2 then
   update crowd_v4.policy set paused=true,version=version+1 where not paused;
   if found then insert into crowd_v4.audit(action,payload) values('automatic_pause','{"reason":"multiple_rate_limits"}');end if;
   result:=result||jsonb_build_object('paused',true);
  end if;
 end if;
 return result;
end $$;
revoke all on function public.crowd_v4_guard(text,bigint,text) from public,anon;
grant execute on function public.crowd_v4_guard(text,bigint,text) to authenticated;

create function public.crowd_v4_profile_claim(p_parent uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); f crowd_v4.proofs; r crowd_v4.receipts; a crowd_observation.profile_attempts; b crowd_observation.profile_budget; g jsonb; d date:=(now() at time zone 'Asia/Shanghai')::date;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 perform 1 from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4' for update;
 if not found then raise exception 'approval_required' using errcode='42501'; end if;
 if not exists(select from crowd_observation.preferences where user_id=u and profiles) then return jsonb_build_object('allowed',false,'reason','consent_required'); end if;
 select * into r from crowd_v4.receipts rec where rec.user_id=u and rec.request=p_parent and rec.result->>'inserted'='true';
 select * into f from crowd_v4.proofs where user_id=u and note_id=r.payload#>>'{record,standard,note_id}';
 if f.id is null or f.record#>>'{extra,author,id}' is null then return jsonb_build_object('allowed',false,'reason','author_missing'); end if;
 insert into crowd_observation.profile_budget(user_id,day) values(u,d) on conflict do nothing;
 select * into b from crowd_observation.profile_budget where user_id=u for update;
 if b.day<d then b.day:=d;b.attempts:=0;end if;
 if b.attempts>=2 then return jsonb_build_object('allowed',false,'reason','profile_budget'); end if;
 -- Cache reservation is global per author, not per browser. Failed attempts are cached too.
 insert into crowd_observation.profile_attempts(author_id,user_id,parent_request) values(f.record#>>'{extra,author,id}',u,p_parent)
 on conflict(author_id) do update set user_id=u,parent_request=p_parent,token=gen_random_uuid(),attempted_at=now()
 where crowd_observation.profile_attempts.attempted_at<now()-interval '24 hours' returning * into a;
 if a.author_id is null then return jsonb_build_object('allowed',false,'reason','profile_cached'); end if;
 g:=crowd_observation.guard_internal('profile',f.task_id,f.note_id);
 if g->>'allowed' is distinct from 'true' then delete from crowd_observation.profile_attempts where token=a.token;return jsonb_build_object('allowed',false,'reason',coalesce(g->>'reason',g->>'error'));end if;
 update crowd_observation.profile_budget set day=d,attempts=b.attempts+1 where user_id=u;
 return jsonb_build_object('allowed',true,'url','https://www.xiaohongshu.com/user/profile/'||a.author_id,'token',a.token);
end $$;

create function public.crowd_v4_observe(p_request uuid,p_parent uuid,p_kind text,p_data jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); old crowd_observation.receipts; r crowd_v4.receipts; f crowd_v4.proofs; result jsonb; error text; capture timestamptz; item jsonb; a text;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 perform 1 from crowd_v4.participants where user_id=u for update;
 if not found then raise exception 'approval_required' using errcode='42501';end if;
 select * into old from crowd_observation.receipts where user_id=u and request=p_request;
 if old.request is not null then
  if old.data is distinct from p_data or old.kind is distinct from p_kind or old.parent_request is distinct from p_parent then return jsonb_build_object('request',p_request,'gate','rejected','error','request_reused');end if;
  return old.result;
 end if;
 if not exists(select from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4') then raise exception 'approval_required' using errcode='42501';end if;
 if p_request is null or p_parent is null or p_kind is null or p_kind not in ('note','profile') or jsonb_typeof(p_data) is distinct from 'object' or octet_length(p_data::text)>180000 then return jsonb_build_object('request',p_request,'gate','rejected','error','invalid_record');end if;
 select * into r from crowd_v4.receipts rec where rec.user_id=u and rec.request=p_parent and rec.result->>'inserted'='true';
 select * into f from crowd_v4.proofs where user_id=u and note_id=r.payload#>>'{record,standard,note_id}';
 if f.id is null then return jsonb_build_object('request',p_request,'gate','rejected','error','parent_missing');end if;
 if exists(select from crowd_observation.snapshots where user_id=u and parent_request=p_parent and kind=p_kind) then error:='already_observed';
 elsif p_kind='note' then
  result:=crowd_observation.validate_note(p_data,f.task_id);error:=result->>'error';
  if p_data#>>'{standard,note_id}' is distinct from f.note_id or p_data->'evidence' is distinct from f.record->'evidence'
    or p_data#>>'{standard,title}' is distinct from f.record#>>'{standard,title}' or p_data#>'{extra,author}' is distinct from f.record#>'{extra,author}' then error:='invalid_record';end if;
  begin capture:=(p_data#>>'{standard,captured_at}')::timestamptz;exception when others then error:='invalid_timestamp';end;
 else
  if not exists(select from crowd_observation.preferences where user_id=u and profiles) then error:='consent_required';end if;
  a:=f.record#>>'{extra,author,id}';
  if a is null or p_data->>'author_id' is distinct from a or p_data->>'url' is distinct from ('https://www.xiaohongshu.com/user/profile/'||a)
   or p_data->>'source' is distinct from 'rendered_public_dom' or coalesce(p_data->>'parser_version','') !~ '^4[.][0-9]+[.][0-9]+$'
   or jsonb_typeof(p_data->'nickname') is distinct from 'string' or length(p_data->>'nickname') not between 1 and 100
   or (p_data-array['author_id','url','nickname','public_handle','captured_at','source','parser_version','metrics','notes','grant'])<>'{}'::jsonb
   or (p_data ? 'public_handle' and (jsonb_typeof(p_data->'public_handle') not in ('string','null') or length(p_data->>'public_handle')>100))
   or jsonb_typeof(p_data->'metrics') is distinct from 'object' or jsonb_typeof(p_data->'notes') is distinct from 'array'
   or octet_length(p_data::text)>16000
   or not exists(select from crowd_observation.profile_attempts where user_id=u and parent_request=p_parent and token::text=p_data->>'grant' and attempted_at>now()-interval '24 hours')
  then error:='invalid_record';end if;
  if error is null then
   if ((p_data->'metrics')-array['followers','notes','likes_collected'])<>'{}'::jsonb or jsonb_array_length(p_data->'notes')>12 then error:='invalid_record';end if;
   for item in select value from jsonb_each(p_data->'metrics') loop
    if jsonb_typeof(item) is distinct from 'object' or coalesce(item->>'status','') not in ('exact','approximate','not_visible','unparsed')
      or jsonb_typeof(item->'value') not in ('null','number') or not(item ? 'value') or (item->'value'<>'null'::jsonb and coalesce(item->>'value','') !~ '^[0-9]{1,10}$') or length(item->>'label')>100 then error:='invalid_record';end if;
   end loop;
   for item in select value from jsonb_array_elements(p_data->'notes') loop
    if coalesce(item->>'note_id','') !~ '^[a-f0-9]{24}$' or jsonb_typeof(item->'title') is distinct from 'string' or length(item->>'title')>300 then error:='invalid_record';end if;
   end loop;
  end if;
  begin capture:=(p_data->>'captured_at')::timestamptz;exception when others then error:='invalid_timestamp';end;
 end if;
 if error is null and (capture is null or capture>now()+interval '5 minutes' or capture<now()-interval '24 hours') then error:='invalid_timestamp';end if;
 result:=jsonb_build_object('request',p_request,'gate',case when error is null then 'observed' else 'rejected' end,'error',error);
 if error is null then
  insert into crowd_observation.snapshots(request,user_id,parent_request,note_id,kind,data,captured_at) values(p_request,u,p_parent,f.note_id,p_kind,p_data,capture);
  if p_kind='profile' then update crowd_observation.authors set nickname=p_data->>'nickname',last_seen=now() where author_id=a;end if;
 end if;
 insert into crowd_observation.receipts(user_id,request,parent_request,kind,data,result) values(u,p_request,p_parent,p_kind,p_data,result);
 return result;
end $$;
revoke all on function public.crowd_v4_observation_preferences(boolean),public.crowd_v4_profile_claim(uuid),public.crowd_v4_observe(uuid,uuid,text,jsonb) from public,anon;
grant execute on function public.crowd_v4_observation_preferences(boolean),public.crowd_v4_profile_claim(uuid),public.crowd_v4_observe(uuid,uuid,text,jsonb) to authenticated;
-- New phase only, no new text/URL/identity telemetry.
do $$ declare def text; begin
 def:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 def:=replace(def,$s$'reopen_note'$s$,$s$'reopen_note','enrich'$s$);
 execute def;
end $$;
commit;
