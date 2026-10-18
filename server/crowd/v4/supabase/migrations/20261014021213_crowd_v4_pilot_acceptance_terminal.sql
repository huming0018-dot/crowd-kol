begin;

-- Report the participant's completed acceptance before an individually full task.
-- Invitation/cohort validity and the original proof budgets remain authoritative.
do $migration$
declare definition text;
full_line text:=$a$ if exists(select from crowd_v4.tasks where id=task and (received>=target or status in ('complete','exhausted','closed'))) then return 'task_full'; end if;$a$;
acceptance_line text:=$a$ if experiment.phase='awaiting_acceptance' and (select count(*) from crowd_v4.proofs p join crowd_v4.pilot_task_map m on m.task_id=p.task_id where p.user_id=participant and m.invite_hash=cohort)>=2 then return 'test_completed'; end if;$a$;
anchor text;
begin
 definition:=pg_get_functiondef('crowd_v4.pilot_block_reason(bigint,uuid)'::regprocedure);
 anchor:=full_line||E'\n'||acceptance_line;
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>1 then raise exception 'pilot_terminal_reason_anchor_mismatch'; end if;
 execute replace(definition,anchor,acceptance_line||E'\n'||full_line);
end $migration$;

-- A completed acceptance is not a quota reset tomorrow. This read-only return
-- runs after approval/consent, before daily quota or any task lease mutation.
do $migration$
declare definition text;
anchor text:=$a$ if p.consent is distinct from 'crowd-public-v4' then raise exception 'consent_required'; end if;$a$;
addition text:=$a$
 if crowd_v4.pilot_phase(u)='awaiting_acceptance' and crowd_v4.pilot_block_reason(null::bigint,u)='test_completed' then
  return jsonb_build_object('error','test_completed','pilot_phase','awaiting_acceptance');
 end if;$a$;
begin
 definition:=pg_get_functiondef('public.crowd_v4_claim(bigint)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>1
  or position(addition in definition)>0 then raise exception 'pilot_terminal_claim_anchor_mismatch'; end if;
 execute replace(definition,anchor,anchor||addition);
end $migration$;

commit;
