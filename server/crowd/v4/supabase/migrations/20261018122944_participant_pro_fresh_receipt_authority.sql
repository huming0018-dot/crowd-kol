-- Existing exact request receipts remain readable. A new UUID needs a live batch.
begin;
do $patch$
declare original text;changed text;
begin
 original:=pg_get_functiondef('public.crowd_v4_pro_submit(bigint,uuid,uuid,jsonb,uuid)'::regprocedure);
 if md5(original)<>'30a9108d89ecee7a1af2f20b89e256ff' then raise exception 'pro_receipt_authority_drift';end if;
 changed:=replace(original,$old$ if not exists(select from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4')$old$,$new$ if exists(select from crowd_v4.participant_pro_batches where task_id=p_task) then
  t:=crowd_observation.pro_scope(p_task,p_installation_id,p_lease,true);
 end if;
 if not exists(select from crowd_v4.participants where user_id=u and status='approved' and consent='crowd-public-v4')$new$);
 if changed=original then raise exception 'pro_receipt_authority_patch_missing';end if;execute changed;
end $patch$;
commit;

