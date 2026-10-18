CREATE OR REPLACE FUNCTION crowd_observation.pro_scope(p_task bigint, p_installation_id uuid, p_lease uuid DEFAULT NULL::uuid, p_live boolean DEFAULT false, p_recovery boolean DEFAULT false)
 RETURNS crowd_v4.tasks
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare u uuid:=auth.uid();t crowd_v4.tasks;g jsonb;
begin
 if u is null then raise exception 'login_required' using errcode='42501';end if;
 perform 1 from crowd_v4.participants where user_id=u for update;
 if not found then raise exception 'approval_required';end if;
 select * into t from crowd_v4.tasks where id=p_task for update;
 if exists(select from crowd_v4.participant_pro_batches where task_id=p_task) then
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
 if p_task is distinct from 19 or t.id is null or t.claimed_by is distinct from u or t.target<>22 or t.received not between 20 and 22
  or not exists(select from crowd_v4.nodes where installation_id=p_installation_id and user_id=u)
  or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=u)
  or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>u) then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_recovery then
  if not exists(select from crowd_v4.acceptance_supplements where task_id=p_task and user_id=u and installation_id=p_installation_id and id='8df461ae-cdff-4476-bc03-47126d6eaecf'::uuid) then raise exception 'pro_scope_denied';end if;return t;
 end if;
 g:=crowd_v4.acceptance_supplement_view(p_task,u);
 if g->>'schema' is distinct from 'crowd-acceptance-batch-v1' or g->>'installation_id' is distinct from p_installation_id::text or g->>'id' is distinct from '8df461ae-cdff-4476-bc03-47126d6eaecf' or g->'baseline_received' is distinct from '2'::jsonb or g->'extra_limit' is distinct from '20'::jsonb or g->'target' is distinct from '22'::jsonb then raise exception 'pro_scope_denied' using errcode='42501';end if;
 if p_lease is not null and (t.lease_token is distinct from p_lease or not exists(select from crowd_v4.node_runs where installation_id=p_installation_id and user_id=u and task_id=p_task and lease_token=p_lease)) then raise exception 'lease_lost';end if;
 if p_live and (p_lease is null or t.status<>'leased' or t.lease_until is null or t.lease_until<=now()) then raise exception 'lease_expired';end if;
 return t;
end $function$
