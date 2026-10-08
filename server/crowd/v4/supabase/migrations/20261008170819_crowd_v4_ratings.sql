begin;
-- Restore the original optional human rating, anchored to a received note.
-- Ratings are separate from factual evidence and do not change note rewards.
create table crowd_v4.ratings (
 user_id uuid not null references crowd_v4.participants(user_id),
 request uuid not null, proof_id bigint not null references crowd_v4.proofs(id),
 task_id bigint not null references crowd_v4.tasks(id),
 score int not null check(score between 1 and 5),
 reason text not null check(length(reason) between 8 and 200),
 created_at timestamptz not null default now(),
 primary key(user_id,task_id), unique(user_id,request)
);
alter table crowd_v4.ratings enable row level security;
revoke all on crowd_v4.ratings from public,anon,authenticated;

create function public.crowd_v4_rating(p_request uuid,p_proof bigint,p_score int,p_reason text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid(); r crowd_v4.ratings; p crowd_v4.participants; target bigint;
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 select * into p from crowd_v4.participants where user_id=u for update;
 if p.status is distinct from 'approved' or p.consent is distinct from 'crowd-public-v4' then raise exception 'approval_required' using errcode='42501'; end if;
 if p_request is null or p_proof is null or p_score is null or p_score not between 1 and 5 or p_reason is null or length(p_reason)>200 or length(regexp_replace(p_reason,'[[:space:][:punct:]]','','g'))<8 then
  return jsonb_build_object('request',p_request,'gate','rejected','error','invalid_rating');
 end if;
 select * into r from crowd_v4.ratings where user_id=u and request=p_request;
 if found then
  if r.proof_id<>p_proof or r.score<>p_score or r.reason<>p_reason then return jsonb_build_object('request',p_request,'gate','rejected','error','request_reused'); end if;
  return jsonb_build_object('request',p_request,'gate','rated','inserted',false);
 end if;
 select task_id into target from crowd_v4.proofs where id=p_proof and user_id=u and status in ('received','verified');
 if target is null then
  return jsonb_build_object('request',p_request,'gate','rejected','error','invalid_anchor');
 end if;
 if exists(select from crowd_v4.ratings where user_id=u and task_id=target) then
  return jsonb_build_object('request',p_request,'gate','rejected','error','already_rated');
 end if;
 insert into crowd_v4.ratings(user_id,request,proof_id,task_id,score,reason) values(u,p_request,p_proof,target,p_score,p_reason);
 return jsonb_build_object('request',p_request,'gate','rated','inserted',true);
end $$;

create function public.crowd_v4_progress() returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=auth.uid();
begin
 if u is null then raise exception 'login_required' using errcode='42501'; end if;
 return jsonb_build_object(
 'tasks',(select coalesce(jsonb_agg(q),'[]'::jsonb) from (
  select t.id,t.query,t.target,t.received,t.status,
   (select count(*) from crowd_v4.proofs p where p.task_id=t.id and p.user_id=u) as own_received
  from crowd_v4.tasks t where t.claimed_by=u or exists(select from crowd_v4.proofs p where p.task_id=t.id and p.user_id=u)
  order by t.id desc limit 20) q),
 'ratings',(select coalesce(jsonb_agg(q),'[]'::jsonb) from (
  select distinct on (p.task_id) p.task_id,p.id as proof_id,p.note_id,left(p.record#>>'{standard,title}',300) as title,
   coalesce(t.store_name,t.query) as subject,r.score,r.reason
  from crowd_v4.proofs p join crowd_v4.tasks t on t.id=p.task_id
  left join crowd_v4.ratings r on r.user_id=u and r.task_id=p.task_id
  where p.user_id=u and p.status in ('received','verified') and (r.proof_id is null or r.proof_id=p.id)
  order by p.task_id desc,p.received_at desc,p.id desc limit 20) q));
end $$;
revoke all on function public.crowd_v4_rating(uuid,bigint,int,text),public.crowd_v4_progress() from public,anon;
grant execute on function public.crowd_v4_rating(uuid,bigint,int,text),public.crowd_v4_progress() to authenticated;
commit;
