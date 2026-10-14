begin;
-- A fully received body task can be acknowledged after its lease expires.
-- No new collection, lease renewal, or completion of comment repair is granted.
do $migration$
declare definition text;
 anchor text := '  if t.lease_until is null or t.lease_until<now() then return jsonb_build_object(''error'',''lease_lost''); end if;';
 replacement text := $replacement$  if t.lease_until is null or (t.lease_until<now() and ((
   t.target>0 and t.received>=t.target and t.comments_capture is false
   and t.structured_capture is false and cardinality(t.comment_repair_parents)=0
  ) is not true)) then return jsonb_build_object('error','lease_lost'); end if;$replacement$;
begin
 definition:=pg_get_functiondef('public.crowd_v4_finish(bigint,uuid)'::regprocedure);
 if (length(definition)-length(replace(definition,anchor,'')))/length(anchor)<>1 then
  raise exception 'received_finish_anchor_mismatch';
 end if;
 execute replace(definition,anchor,replacement);
end $migration$;
commit;
