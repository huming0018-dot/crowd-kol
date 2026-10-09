begin;
-- A search pass is not proof that a keyword is permanently exhausted.
-- Keep the existing RPC signatures so installed v4 clients remain compatible.
alter table crowd_v4.tasks
 add column available_at timestamptz not null default now(),
 add column last_claimed_at timestamptz,
 add column empty_passes integer not null default 0 check(empty_passes between 0 and 6),
 add column lease_start_received integer not null default 0;
update crowd_v4.tasks set lease_start_received=received,
 last_claimed_at=case when status='leased' then coalesce(lease_until-interval '20 minutes',created_at) else null end;
-- Retain historical exhausted/closed decisions; reopening requires operator review.
create index tasks_dispatch on crowd_v4.tasks(last_claimed_at nulls first,id) where status in ('open','leased');
create or replace function public.crowd_v4_claim(p_task bigint default null) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid := auth.uid(); p crowd_v4.participants; t crowd_v4.tasks; n int;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' then raise exception 'approval_required' using errcode='42501'; end if;
 if p.consent is distinct from 'crowd-public-v4' then raise exception 'consent_required'; end if;
 select count(*) into n from crowd_v4.proofs where user_id=u and received_at>=date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai';
 if n>=p.quota_day then return jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint); end if;
 -- Same owner renews an existing lease before receiving another task.
 select * into t from crowd_v4.tasks where claimed_by=u and status='leased' and (p_task is null or id=p_task) order by id limit 1 for update;
 if t.id is null then
  if p_task is not null then return jsonb_build_object('task',null); end if;
  select * into t from crowd_v4.tasks where received<target and ((status='open' and available_at<=now()) or (status='leased' and lease_until<now())) order by last_claimed_at nulls first,id limit 1 for update skip locked;
 end if;
 if t.id is null then return jsonb_build_object('task',null); end if;
 update crowd_v4.tasks set last_claimed_at=case when status='leased' and claimed_by=u then last_claimed_at else now() end,
 lease_start_received=case when status='leased' and claimed_by=u then lease_start_received else received end,
 status='leased',claimed_by=u,lease_token=case when status='leased' and claimed_by=u then coalesce(lease_token,gen_random_uuid()) else gen_random_uuid() end,
 lease_until=now()+interval '20 minutes' where id=t.id returning * into t;
 return jsonb_build_object('task',(to_jsonb(t)-'claimed_by'-'source_key')||jsonb_build_object('remaining_today',p.quota_day-n,
 'known_note_ids',(select coalesce(jsonb_agg(known.note_id),'[]'::jsonb) from (
   select f.note_id from crowd_v4.proofs f join crowd_v4.tasks source on source.id=f.task_id
   where source.query=t.query order by f.id desc limit 500
 ) known)));
end $$;
create or replace function public.crowd_v4_finish(p_task bigint,p_lease uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); t crowd_v4.tasks; empty_count int;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 perform 1 from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4' for update;
 if not found then raise exception 'approval_required' using errcode='42501'; end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if t.id is null or p_lease is null or t.claimed_by is distinct from u or t.lease_token is distinct from p_lease then
  return jsonb_build_object('error','lease_lost');
 end if;
 -- A lost finish response may be replayed, but only until a NEW lease rotates the token.
 if t.status='leased' then
  if t.lease_until is null or t.lease_until<now() then return jsonb_build_object('error','lease_lost'); end if;
  empty_count:=case when t.received>t.lease_start_received then 0 else least(t.empty_passes+1,6) end;
  update crowd_v4.tasks set status=case when received>=target then 'complete' else 'open' end,
   empty_passes=empty_count,
   available_at=now()+make_interval(mins=>least(360,15*(2^greatest(0,empty_count-1))::int))
   where id=p_task returning * into t;
 end if;
 return jsonb_build_object('status',t.status,'received',t.received,'available_at',t.available_at);
end $$;
revoke all on function public.crowd_v4_claim(bigint),public.crowd_v4_finish(bigint,uuid) from public,anon,authenticated;
grant execute on function public.crowd_v4_claim(bigint),public.crowd_v4_finish(bigint,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
