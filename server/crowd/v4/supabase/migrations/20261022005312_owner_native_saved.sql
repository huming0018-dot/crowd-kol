-- Owner-native public-content intake. No task, lease, capture or reward is created.
create schema if not exists crowd_machine;
create function crowd_machine.native_saved_keys(v jsonb, keys text[]) returns boolean
language sql immutable set search_path='' as $$
 select case when jsonb_typeof(v)='object' then (select count(*) from jsonb_object_keys(v))=cardinality(keys) and v ?& keys else false end
$$;
create function crowd_machine.native_saved_canonical(v jsonb) returns text
language plpgsql immutable set search_path='' as $$
declare t text:=jsonb_typeof(v); s text; out text:=''; ch text; n integer; pair record;
begin
 if t='null' then return 'null'; elsif t='boolean' then return v::text;
 elsif t='number' then
  s:=v::text; if s !~ '^-?(0|[1-9][0-9]*)$' or abs(s::numeric)>9007199254740991 then raise exception 'invalid_native_saved'; end if;
  return case when s::numeric=0 then '0' else s end;
 elsif t='string' then
  s:=v#>>'{}'; for n in 1..length(s) loop ch:=substr(s,n,1);
   if ch='"' then out:=out||E'\\"'; elsif ch=E'\\' then out:=out||E'\\\\'; elsif ascii(ch)<32 then out:=out||E'\\u'||lpad(to_hex(ascii(ch)),4,'0'); else out:=out||ch; end if;
  end loop; return '"'||out||'"';
 elsif t='array' then
  for pair in select value from jsonb_array_elements(v) loop out:=out||case when out='' then '' else ',' end||crowd_machine.native_saved_canonical(pair.value); end loop;return '['||out||']';
 elsif t='object' then
  for pair in select key,value from jsonb_each(v) order by key collate "C" loop out:=out||case when out='' then '' else ',' end||crowd_machine.native_saved_canonical(to_jsonb(pair.key))||':'||crowd_machine.native_saved_canonical(pair.value); end loop;return '{'||out||'}';
 end if; raise exception 'invalid_native_saved';
end $$;
create table crowd_machine.native_import_batches(
 batch_id uuid primary key default gen_random_uuid(),owner_scope text not null check(owner_scope='crowd-owner-main'),
 idempotency_key text not null, batch_hash text not null check(batch_hash ~ '^[a-f0-9]{64}$'),
 snapshot_sha256 text not null check(snapshot_sha256 ~ '^[a-f0-9]{64}$'),canonical_payload text not null,
 envelope jsonb not null,receipt jsonb not null,created_at timestamptz not null default now(),unique(owner_scope,idempotency_key)
);
create table crowd_machine.native_import_records(
 batch_id uuid not null references crowd_machine.native_import_batches(batch_id),native_table text not null check(native_table in('xhs_note','xhs_note_comment')),
 native_id text not null,record_sha256 text not null check(record_sha256 ~ '^[a-f0-9]{64}$'),native_row_sha256 text not null check(native_row_sha256 ~ '^[a-f0-9]{64}$'),
 raw_record jsonb not null,url_redaction jsonb not null,primary key(batch_id,native_table,native_id)
);
alter table crowd_machine.native_import_batches enable row level security;
alter table crowd_machine.native_import_records enable row level security;
revoke all on crowd_machine.native_import_batches,crowd_machine.native_import_records from public,anon,authenticated,service_role;
grant select on crowd_machine.native_import_batches,crowd_machine.native_import_records to service_role;
create function crowd_machine.native_saved_immutable() returns trigger language plpgsql set search_path='' as $$begin raise exception 'native_saved_immutable'; end$$;
create trigger native_import_batches_immutable before update or delete on crowd_machine.native_import_batches for each row execute function crowd_machine.native_saved_immutable();
create trigger native_import_records_immutable before update or delete on crowd_machine.native_import_records for each row execute function crowd_machine.native_saved_immutable();
create function public.crowd_owner_native_saved_rpc(p_owner_scope text,p_actor_kind text,p_action text,p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare env jsonb; src jsonb; items jsonb; itm jsonb; r jsonb; red jsonb; col text; cols text[]; val jsonb;
 nid text; note_id text; parent text; visited text[]; par jsonb; sem text; key text; h text; bid uuid; stamp timestamptz:=now(); old crowd_machine.native_import_batches%rowtype;
 hashes jsonb:='[]'; redacted jsonb:='[]'; receipt jsonb;
begin
 if p_owner_scope is distinct from 'crowd-owner-main' or p_actor_kind is distinct from 'owner' then raise exception 'principal_denied'; end if;
 if p_action='native_saved_get' then
  if not crowd_machine.native_saved_keys(p_payload,array['idempotency_key']) then raise exception 'invalid_native_saved'; end if;
  key:=p_payload->>'idempotency_key';
  if jsonb_typeof(p_payload->'idempotency_key') is distinct from 'string' or length(key) not between 1 and 160 or key ~ '[\x00-\x1f]' then raise exception 'invalid_native_saved'; end if;
  select * into old from crowd_machine.native_import_batches where owner_scope=p_owner_scope and idempotency_key=key;
  if not found then raise exception 'native_saved_not_found'; end if;
  return jsonb_build_object('native_saved',old.receipt,'replayed',false,'content',old.envelope);
 end if;
 if p_action is distinct from 'native_saved_put' or not crowd_machine.native_saved_keys(p_payload,array['envelope','canonical_payload','batch_hash']) then raise exception 'invalid_native_saved'; end if;
 env:=p_payload->'envelope';sem:=p_payload->>'canonical_payload';h:=p_payload->>'batch_hash';
 if sem is null or octet_length(sem)>250000 or sem is distinct from crowd_machine.native_saved_canonical(env) or h is distinct from encode(sha256(convert_to(E'crowd-owner-native-batch-v1\n'||sem,'UTF8')),'hex') then raise exception 'native_saved_hash_mismatch'; end if;
 if not crowd_machine.native_saved_keys(env,array['schema','idempotency_key','source','records']) or env->>'schema' is distinct from 'crowd-owner-native-saved-v1' then raise exception 'invalid_native_saved'; end if;
 key:=env->>'idempotency_key';if jsonb_typeof(env->'idempotency_key') is distinct from 'string' or length(key) not between 1 and 160 or key ~ '[\x00-\x1f]' then raise exception 'invalid_native_saved'; end if;
 src:=env->'source';items:=env->'records';
 if not crowd_machine.native_saved_keys(src,array['platform','kind','sdk_commit','snapshot_sha256']) or exists(select 1 from jsonb_each(src) where jsonb_typeof(value)<>'string') or src->>'platform' is distinct from 'xiaohongshu' or src->>'kind' is distinct from 'mediacrawler_pro_native_sqlite' or coalesce(src->>'sdk_commit','') !~ '^[a-f0-9]{40}$' or coalesce(src->>'snapshot_sha256','') !~ '^[a-f0-9]{64}$' then raise exception 'invalid_native_saved'; end if;
 if jsonb_typeof(items) is distinct from 'array' then raise exception 'invalid_native_saved'; end if;
 if jsonb_array_length(items) not between 1 and 1000 then raise exception 'invalid_native_saved'; end if;
 for itm in select value from jsonb_array_elements(items) loop
  if not crowd_machine.native_saved_keys(itm,array['native_table','native_id','record','native_row_sha256','url_redaction','record_sha256']) or jsonb_typeof(itm->'native_table') is distinct from 'string' or jsonb_typeof(itm->'native_id') is distinct from 'string' or jsonb_typeof(itm->'native_row_sha256') is distinct from 'string' or jsonb_typeof(itm->'record_sha256') is distinct from 'string' or itm->>'native_table' not in('xhs_note','xhs_note_comment') or coalesce(itm->>'native_id','') !~ '^[A-Za-z0-9_-]{1,100}$' or coalesce(itm->>'native_row_sha256','') !~ '^[a-f0-9]{64}$' or coalesce(itm->>'record_sha256','') !~ '^[a-f0-9]{64}$' then raise exception 'invalid_native_saved'; end if;
  r:=itm->'record';nid:=itm->>'native_id';
  cols:=case when itm->>'native_table'='xhs_note' then array['id','nickname','creator_hash','add_ts','last_modify_ts','note_id','type','title','desc','video_url','time','last_update_time','liked_count','collected_count','comment_count','share_count','image_list','tag_list','note_url','source_keyword'] else array['id','nickname','creator_hash','add_ts','last_modify_ts','comment_id','create_time','note_id','content','sub_comment_count','pictures','parent_comment_id','like_count','note_url','target_comment_id'] end;
  if not crowd_machine.native_saved_keys(r,cols) then raise exception 'invalid_native_saved'; end if;
  foreach col in array cols loop
   val:=r->col;
   if col=any(array['id','add_ts','last_modify_ts','time','last_update_time','create_time']) then
    if jsonb_typeof(val) is distinct from 'number' or val::text !~ '^-?(0|[1-9][0-9]*)$' then raise exception 'invalid_native_saved'; end if;
    if abs((val::text)::numeric)>9007199254740991 then raise exception 'invalid_native_saved'; end if;
   elsif jsonb_typeof(val) is distinct from 'string' and not(val='null'::jsonb and col<>all(array['note_id','comment_id','content','sub_comment_count','like_count'])) then raise exception 'invalid_native_saved';
   elsif jsonb_typeof(val)='string' and length(val#>>'{}')>100000 then raise exception 'invalid_native_saved'; end if;
  end loop;
  if nid is distinct from r->>(case when itm->>'native_table'='xhs_note' then 'note_id' else 'comment_id' end) or coalesce(r->>'note_url','') !~ '^https?://(www\.)?xiaohongshu\.com/explore/[A-Za-z0-9_-]+/?$' then raise exception 'invalid_native_saved'; end if;
  red:=itm->'url_redaction';
  if not crowd_machine.native_saved_keys(red,array['field','original_url_sha256','removed_query_keys','removed_fragment']) or jsonb_typeof(red->'original_url_sha256') is distinct from 'string' or red->>'field' is distinct from 'note_url' or coalesce(red->>'original_url_sha256','') !~ '^[a-f0-9]{64}$' or jsonb_typeof(red->'removed_fragment') is distinct from 'boolean' or jsonb_typeof(red->'removed_query_keys') is distinct from 'array' then raise exception 'invalid_native_saved'; end if;
  if jsonb_array_length(red->'removed_query_keys')>32 or exists(select 1 from jsonb_array_elements(red->'removed_query_keys') q where jsonb_typeof(q) is distinct from 'string' or q#>>'{}' !~ '^[A-Za-z0-9_.-]{1,80}$') or red->'removed_query_keys' is distinct from (select coalesce(jsonb_agg(k order by k collate "C"),'[]'::jsonb) from(select distinct q#>>'{}' k from jsonb_array_elements(red->'removed_query_keys') q) u) then raise exception 'invalid_native_saved'; end if;
  if r::text ~* '(cookie|authorization|password|access_token|refresh_token|private_key)\s*[=:]|[?&](xsec_token|xsec_source|access_token|token)=' then raise exception 'sensitive_native_saved'; end if;
  if itm->>'record_sha256' is distinct from encode(sha256(convert_to(E'crowd-owner-native-record-v1\n'||crowd_machine.native_saved_canonical(jsonb_build_object('native_table',itm->'native_table','native_id',itm->'native_id','record',r)),'UTF8')),'hex') then raise exception 'native_saved_hash_mismatch'; end if;
  if itm->>'native_table'='xhs_note' then if note_id is not null then raise exception 'invalid_native_saved'; end if; note_id:=nid;end if;
  hashes:=hashes||jsonb_build_array(jsonb_build_object('native_table',itm->'native_table','native_id',nid,'record_sha256',itm->'record_sha256'));
  if red->'removed_query_keys'<>'[]'::jsonb or red->'removed_fragment'='true'::jsonb then redacted:=redacted||jsonb_build_array(jsonb_build_object('native_table',itm->'native_table','native_id',nid,'field','note_url'));end if;
 end loop;
 if note_id is null or exists(select 1 from jsonb_array_elements(items) i group by i->>'native_table',i->>'native_id' having count(*)>1) then raise exception 'invalid_native_saved'; end if;
 for itm in select value from jsonb_array_elements(items) where value->>'native_table'='xhs_note_comment' loop
  if itm->'record'->>'note_id' is distinct from note_id then raise exception 'invalid_native_saved';end if;
  parent:=itm->'record'->>'parent_comment_id';visited:=array[itm->>'native_id'];
  while parent is not null and parent not in('','0') loop
   if parent=any(visited) then raise exception 'invalid_native_saved';end if;visited:=array_append(visited,parent);
   select value into par from jsonb_array_elements(items) where value->>'native_table'='xhs_note_comment' and value->>'native_id'=parent;
   if not found then raise exception 'invalid_native_saved';end if;parent:=par->'record'->>'parent_comment_id';
  end loop;
 end loop;
 perform pg_advisory_xact_lock(hashtextextended(p_owner_scope||E'\n'||key,0));
 select * into old from crowd_machine.native_import_batches where owner_scope=p_owner_scope and idempotency_key=key;
 if found then if old.batch_hash<>h or old.canonical_payload<>sem then raise exception 'native_saved_conflict';end if;return jsonb_build_object('native_saved',old.receipt,'replayed',true);end if;
 bid:=gen_random_uuid();receipt:=jsonb_build_object('schema','crowd-owner-native-saved-receipt-v1','batch_id',bid,'batch_hash',h,'snapshot_sha256',src->'snapshot_sha256','record_count',jsonb_array_length(items),'record_hashes',hashes,'redacted_fields',redacted,'created_at',stamp,'source_kind','native_saved','reward_eligible',false);
 insert into crowd_machine.native_import_batches(batch_id,owner_scope,idempotency_key,batch_hash,snapshot_sha256,canonical_payload,envelope,receipt,created_at) values(bid,p_owner_scope,key,h,src->>'snapshot_sha256',sem,env,receipt,stamp);
 for itm in select value from jsonb_array_elements(items) loop insert into crowd_machine.native_import_records values(bid,itm->>'native_table',itm->>'native_id',itm->>'record_sha256',itm->>'native_row_sha256',itm->'record',itm->'url_redaction');end loop;
 return jsonb_build_object('native_saved',receipt,'replayed',false);
end $$;
revoke all on function public.crowd_owner_native_saved_rpc(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.crowd_owner_native_saved_rpc(text,text,text,jsonb) to service_role;
revoke all on function crowd_machine.native_saved_keys(jsonb,text[]),crowd_machine.native_saved_canonical(jsonb),crowd_machine.native_saved_immutable() from public,anon,authenticated,service_role;
