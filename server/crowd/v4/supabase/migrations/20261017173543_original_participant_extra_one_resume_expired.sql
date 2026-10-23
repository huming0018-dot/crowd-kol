-- Root-only candidate. Migration changes one RPC definition, not business data or privileges.
begin;
do $patch$
declare original text;
begin
 original:=pg_get_functiondef('public.crowd_v4_acceptance_supplement(text,uuid,bigint,uuid,uuid,timestamptz)'::regprocedure);
 if md5(original) is distinct from 'e3c24f5ffaf7428a8513587784a23c34' then raise exception 'extra1_resume_definition_drift'; end if;
 if (length(original)-length(replace(original,$n0$baseline jsonb;$n0$,'')))/length($n0$baseline jsonb;$n0$)<>1 then raise exception 'extra1_resume_anchor_mismatch'; end if;
 original:=replace(original,$n0$baseline jsonb;$n0$,$r0$baseline jsonb; resumed jsonb;$r0$);
 if (length(original)-length(replace(original,$n1$p_action not in ('grant','revoke')$n1$,'')))/length($n1$p_action not in ('grant','revoke')$n1$)<>1 then raise exception 'extra1_resume_anchor_mismatch'; end if;
 original:=replace(original,$n1$p_action not in ('grant','revoke')$n1$,$r1$p_action not in ('grant','revoke','resume_expired')$r1$);
 if (length(original)-length(replace(original,$n2$  if p_action='revoke' then
$n2$,'')))/length($n2$  if p_action='revoke' then
$n2$)<>1 then raise exception 'extra1_resume_anchor_mismatch'; end if;
 original:=replace(original,$n2$  if p_action='revoke' then
$n2$,$r2$  if p_action='resume_expired' then
   -- Repair the same unused allowance, never create or replenish one.
   if g.revoked or g.consumed_request is not null or p_expires_at is null
    or p_expires_at is distinct from g.created_at+interval '2 hours' or p_expires_at<=clock_timestamp()
    or (g.expires_at>clock_timestamp() and g.expires_at is distinct from p_expires_at)
    then raise exception 'supplement_resume_denied'; end if;
   select * into t from crowd_v4.tasks where id=p_task for update;
   if t.status is distinct from 'open' or t.target is distinct from 3 or t.received is distinct from 2
    or t.claimed_by is distinct from p_user
    or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>p_user)
    or (select count(*) from crowd_v4.proofs where task_id=p_task)<>2
    or exists(select from crowd_v4.tasks live where live.claimed_by=p_user and live.status='leased' and live.lease_until>now())
    or not exists(select from crowd_v4.nodes where installation_id=p_installation and user_id=p_user
      and version='4.2.76' and release_digest='868d5e6cd29b2a56728005d0f005af4787c6c006bf54105d7698b52cc7176b97'
      and login_state='ready' and updated_at>clock_timestamp()-interval '2 minutes' and updated_at<=clock_timestamp())
    then raise exception 'supplement_resume_denied'; end if;
   if g.expires_at is distinct from p_expires_at then
    update crowd_v4.acceptance_supplements set expires_at=p_expires_at where id=g.id;
   end if;
   resumed:=crowd_v4.acceptance_supplement_view(p_task,p_user);
   if resumed is null or (resumed->>'remaining')::integer is distinct from 1 then
    raise exception 'supplement_resume_baseline_denied';
   end if;
   if g.expires_at is distinct from p_expires_at then
    insert into crowd_v4.audit(action,payload) values('acceptance_supplement_resume_expired',jsonb_build_object(
     'id',g.id,'task_id',g.task_id,'installation_id',g.installation_id,'created_at',g.created_at,
     'previous_expires_at',g.expires_at,'expires_at',p_expires_at,'baseline_received',2,'extra_limit',1,
     'reason','unused_allowance_maintenance_window'));
   end if;
   return jsonb_build_object('id',g.id,'revoked',false,'acceptance_supplement',resumed);
  elsif p_action='revoke' then
$r2$);
 execute original;
end $patch$;
commit;
