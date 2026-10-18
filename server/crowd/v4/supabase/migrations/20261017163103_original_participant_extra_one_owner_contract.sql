-- Root-only schema migration candidate: remove a false positive ownership prerequisite.
-- No data/owner insert or task/proof/receipt mutation. Preserve explicit foreign-owner denial.
begin;
do $patch$
declare original text; patched text;
needle text := $needle$ or not exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id=p_user)
$needle$;
begin
 original:=pg_get_functiondef('public.crowd_v4_acceptance_supplement(text,uuid,bigint,uuid,uuid,timestamptz)'::regprocedure);
 if md5(original) is distinct from '99903eed01aafb5606d5080648bc6a48' then raise exception 'extra1_owner_definition_drift'; end if;
 if (length(original)-length(replace(original,needle,'')))/length(needle)<>1 then raise exception 'extra1_owner_anchor_mismatch'; end if;
 patched:=replace(original,needle,$replacement$ or t.claimed_by is distinct from p_user
$replacement$);
 if position('or exists(select from crowd_v4.test_task_owners where task_id=p_task and user_id<>p_user)' in patched)=0 then raise exception 'extra1_foreign_owner_guard_missing'; end if;
 execute patched;
end $patch$;
commit;
