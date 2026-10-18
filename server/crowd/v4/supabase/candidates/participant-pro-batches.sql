-- Authorization for bounded Pro acceptance tasks; task/dispatch/receipt storage stays original.
begin;
create table crowd_v4.participant_pro_batches(
 id uuid primary key default gen_random_uuid(),
 task_id bigint not null unique references crowd_v4.tasks(id),
 user_id uuid not null references crowd_v4.participants(user_id),
 installation_id uuid not null references crowd_v4.nodes(installation_id),
 invite_hash text not null references crowd_v4.pilot_experiments(invite_hash),
 baseline_task jsonb not null,
 target integer not null check(target between 1 and 100),
 expires_at timestamptz not null,
 revoked boolean not null default false,
 created_at timestamptz not null default now()
);
alter table crowd_v4.participant_pro_batches enable row level security;
revoke all on crowd_v4.participant_pro_batches from public,anon,authenticated;
do $patch$
declare original text; changed text;
begin
 if md5(pg_get_functiondef('crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure))<>'c4b57996dd00288f42056568db07d3c3' then raise exception 'pro_batch_view_drift';end if;
 if md5(pg_get_functiondef('public.crowd_v4_node_claim(uuid,bigint)'::regprocedure))<>'f7de14c1fd2be49c3cce83ba6e87e007' then raise exception 'pro_batch_node_drift';end if;
 if md5(pg_get_functiondef('crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure))<>'d1f7a329805c996902d90dd513696832' then raise exception 'pro_batch_scope_drift';end if;
 original:=pg_get_functiondef('crowd_v4.acceptance_supplement_view(bigint,uuid)'::regprocedure);
 changed:=replace(original,'begin'||chr(10),$body$begin
 -- New batches authorize only their original node/task. Old grants are untouched.
 if exists(select from crowd_v4.participant_pro_batches b join crowd_v4.tasks bt on bt.id=b.task_id
  where b.user_id=participant and (task is null or b.task_id=task) and not b.revoked and b.expires_at>now()
   and (task is not null or bt.received<bt.target)) then
  return (select jsonb_build_object('schema','crowd-acceptance-batch-v1','id',b.id,'task_id',b.task_id,
   'installation_id',b.installation_id,'baseline_received',0,'extra_limit',b.target,'target',b.target,
   'remaining',greatest(0,b.target-bt.received))
   from crowd_v4.participant_pro_batches b join crowd_v4.tasks bt on bt.id=b.task_id
   where b.user_id=participant and (task is null or b.task_id=task) and not b.revoked and b.expires_at>now()
    and (task is not null or bt.received<bt.target)
    and bt.claimed_by=participant and bt.target=b.target and bt.received between 0 and b.target
    and bt.status in ('open','leased','complete') and bt.source_executor='mediacrawler_pro'
    and crowd_v4.acceptance_task_input(bt)=b.baseline_task
    and (select count(*) from crowd_v4.proofs p where p.task_id=bt.id)=bt.received
    and not exists(select from crowd_v4.proofs p where p.task_id=bt.id and p.user_id<>participant)
    and exists(select from crowd_v4.participants p where p.user_id=participant and p.status='approved' and p.consent='crowd-public-v4')
    and exists(select from crowd_v4.nodes n where n.installation_id=b.installation_id and n.user_id=participant)
    and exists(select from crowd_v4.test_task_owners o where o.task_id=bt.id and o.user_id=participant)
    and not exists(select from crowd_v4.test_task_owners o where o.task_id=bt.id and o.user_id<>participant)
    and exists(select from crowd_v4.enrollments e join crowd_v4.pilot_experiments x using(invite_hash)
     join crowd_v4.invites i on i.token_hash=x.invite_hash join crowd_v4.pilot_task_map m on m.invite_hash=x.invite_hash
     where e.user_id=participant and e.completed_at is not null and x.invite_hash=b.invite_hash
      and m.task_id=bt.id and x.phase='awaiting_acceptance' and not i.revoked and i.max_people<=5 and i.quota_day=2)
   order by b.created_at,b.task_id limit 1);
 end if;
$body$);
 if changed=original then raise exception 'pro_batch_view_patch_missing';end if;execute changed;
 original:=pg_get_functiondef('public.crowd_v4_node_claim(uuid,bigint)'::regprocedure);
 changed:=replace(original,$old$if exists(select from crowd_v4.acceptance_supplements g where g.user_id=u and coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0 and (g.installation_id<>p_installation or p_task is not null and g.task_id<>p_task)) then raise exception 'node_binding_denied'; end if;$old$,$new$if coalesce((crowd_v4.acceptance_supplement_view(p_task,u)->>'remaining')::int,0)>0 and
  ((crowd_v4.acceptance_supplement_view(p_task,u)->>'installation_id')::uuid<>p_installation or p_task is not null and (crowd_v4.acceptance_supplement_view(p_task,u)->>'task_id')::bigint<>p_task) then raise exception 'node_binding_denied'; end if;$new$);
 if changed=original then raise exception 'pro_batch_node_patch_missing';end if;execute changed;
 original:=pg_get_functiondef('crowd_observation.pro_scope(bigint,uuid,uuid,boolean,boolean)'::regprocedure);
 changed:=replace(original,$old$ if p_task is distinct from 19$old$,$new$ if exists(select from crowd_v4.participant_pro_batches where task_id=p_task) then
  if t.id is null or t.claimed_by is distinct from u
   or not exists(select from crowd_v4.nodes where installation_id=p_installation_id and user_id=u)
   or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=u)
   or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>u)
   or not exists(select from crowd_v4.participant_pro_batches b where b.task_id=p_task and b.user_id=u
     and b.installation_id=p_installation_id and b.target=t.target and crowd_v4.acceptance_task_input(t)=b.baseline_task)
   then raise exception 'pro_scope_denied' using errcode='42501';end if;
  if not p_recovery and crowd_v4.acceptance_supplement_view(p_task,u) is null then raise exception 'pro_scope_denied' using errcode='42501';end if;
  if p_lease is not null and (t.lease_token is distinct from p_lease or not exists(select from crowd_v4.node_runs where installation_id=p_installation_id and user_id=u and task_id=p_task and lease_token=p_lease)) then raise exception 'lease_lost';end if;
  if p_live and (p_lease is null or t.status<>'leased' or t.lease_until is null or t.lease_until<=now()) then raise exception 'lease_expired';end if;
  return t;
 end if;
 if p_task is distinct from 19$new$);
 if changed=original then raise exception 'pro_batch_scope_patch_missing';end if;execute changed;
end $patch$;
commit;

