begin;
-- v4 has one stable request UUID per record. Quota waits must never become receipts.
-- Keep the already-deployed validation/privilege/receipt-replay logic intact.
do $patch$
declare definition text; signature text;
 old text := $old$jsonb_build_object('error','daily_quota')$old$;
 replacement text := $new$jsonb_build_object('error','daily_quota',
 'reset_at',(date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai',
 'retry_after_ms',ceil(extract(epoch from (((date_trunc('day',now() at time zone 'Asia/Shanghai')+interval '1 day') at time zone 'Asia/Shanghai')-now()))*1000)::bigint)$new$;
begin
 foreach signature in array array['public.crowd_v4_claim(bigint)','public.crowd_v4_submit(uuid,bigint,uuid,jsonb)'] loop
  definition:=pg_get_functiondef(signature::regprocedure);
  if (length(definition)-length(replace(definition,old,'')))/length(old)<>1 then raise exception 'quota_patch_anchor_missing: %',signature; end if;
  execute replace(definition,old,replacement);
 end loop;
 -- A rejected proof still occupies the global note_id UNIQUE key. Reopening it
 -- cannot create another record: skip it before spending a detail visit too.
 definition:=pg_get_functiondef('public.crowd_v4_guard(text,bigint,text)'::regprocedure);
 old:=$old$where note_id=p_note and status<>'rejected'$old$;
 if position(old in definition)=0 then raise exception 'guard_patch_anchor_missing'; end if;
 execute replace(definition,old,'where note_id=p_note');
 definition:=pg_get_functiondef('public.crowd_v4_diagnostics(text,bigint,jsonb)'::regprocedure);
 old:=$old$'note_busy','unexpected_error'$old$;
 if position(old in definition)=0 then raise exception 'diagnostics_patch_anchor_missing'; end if;
 execute replace(definition,old,$new$'note_busy','invalid_receipt','unexpected_error'$new$);
end $patch$;
commit;
